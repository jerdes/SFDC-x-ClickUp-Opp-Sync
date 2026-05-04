// ClickUpClient.gs — All HTTP interactions with the ClickUp REST API v2.
//
// Replaces clickup/client.py. Uses UrlFetchApp instead of requests.Session.

const _MAX_RETRIES = 3;

/**
 * Create a ClickUp API client.
 *
 * @param {string} apiToken  ClickUp API token.
 * @param {string} listId    ClickUp list ID.
 * @param {string} baseUrl   API base URL (default: https://api.clickup.com/api/v2).
 * @returns {object} Client object with methods matching clickup/client.py.
 */
function makeClickUpClient(apiToken, listId, baseUrl) {
  const _base = (baseUrl || 'https://api.clickup.com/api/v2').replace(/\/$/, '');
  const _headers = {
    'Authorization': apiToken,
    'Content-Type': 'application/json',
  };

  // ----------------------------------------------------------------
  // HTTP helpers
  // ----------------------------------------------------------------

  function _request(method, path, body) {
    const url = _base + path;
    const options = {
      method: method.toLowerCase(),
      headers: _headers,
      muteHttpExceptions: true,
    };
    if (body !== undefined) {
      options.payload = JSON.stringify(body);
    }

    let lastError = null;
    for (let attempt = 1; attempt <= _MAX_RETRIES; attempt++) {
      const resp = UrlFetchApp.fetch(url, options);
      const code = resp.getResponseCode();

      if (code === 429) {
        const retryAfter = parseInt((resp.getHeaders()['Retry-After'] || '60'), 10);
        Logger.log(
          'ClickUp rate limit hit (attempt %d/%d). Sleeping %ds.',
          attempt, _MAX_RETRIES, retryAfter
        );
        Utilities.sleep(retryAfter * 1000);
        lastError = new Error('ClickUp API error 429: ' + resp.getContentText());
        continue;
      }

      if (code < 200 || code >= 300) {
        throw new Error('ClickUp API error ' + code + ': ' + resp.getContentText());
      }

      const text = resp.getContentText();
      return text ? JSON.parse(text) : null;
    }

    throw lastError || new Error('ClickUp rate limit exceeded after retries');
  }

  // ----------------------------------------------------------------
  // Public API
  // ----------------------------------------------------------------

  const client = {

    /** Verify the API token is valid. Throws with a helpful message on 401. */
    validateToken() {
      let data;
      try {
        data = _request('GET', '/user');
      } catch (e) {
        if (e.message.includes('401')) {
          throw new Error(
            'Token rejected by ClickUp. Verify CLICKUP_API_TOKEN in Script Properties: ' +
            'go to ClickUp → Settings → Apps → API Token. Original error: ' + e.message
          );
        }
        throw e;
      }
      const user = data.user || {};
      Logger.log('ClickUp token validated: user="%s" (id=%s)', user.username, user.id);
      return user;
    },

    /** Fetch all custom fields defined on the list. */
    getListFields() {
      const data = _request('GET', '/list/' + listId + '/field');
      return data.fields || [];
    },

    /**
     * Fetch every task in the list (including closed and archived).
     * Hydrates individual tasks when custom fields are missing from list responses.
     */
    getAllTasks(sfIdFieldId) {
      let tasks = [];

      // ClickUp v2: archived=true returns ONLY archived tasks. Fetch both passes.
      for (const archived of ['false', 'true']) {
        let page = 0;
        while (true) {
          const path = (
            '/list/' + listId + '/task' +
            '?page=' + page +
            '&include_closed=true' +
            '&archived=' + archived +
            '&subtasks=false'
          );
          const data = _request('GET', path);
          const batch = data.tasks || [];
          tasks = tasks.concat(batch);
          Logger.log('Fetched page %d (archived=%s): %d tasks', page, archived, batch.length);
          if (batch.length === 0) break;
          page++;
        }
      }

      tasks = _hydrateTasks(tasks, sfIdFieldId);
      Logger.log('Fetched %d total tasks from ClickUp list %s', tasks.length, listId);
      return tasks;
    },

    /** Fetch a single task by ID. */
    getTask(taskId) {
      return _request('GET', '/task/' + taskId);
    },

    /** Create a new ClickUp task. Returns the created task dict. */
    createTask(name) {
      const task = _request('POST', '/list/' + listId + '/task', { name: name });
      Logger.log('Created task id=%s name="%s"', task.id, name);
      return task;
    },

    /**
     * Update a task's name and each changed custom field.
     * Uses the dedicated POST /task/{id}/field/{field_id} endpoint for each field,
     * which is more reliable than the PUT body for dropdown types.
     */
    updateTask(taskId, name, customFields) {
      _request('PUT', '/task/' + taskId, { name: name });
      for (const field of customFields) {
        try {
          client.setCustomField(taskId, field.id, field.value);
        } catch (e) {
          Logger.log(
            'WARNING: Could not update field %s on task %s (value=%s): %s',
            field.id, taskId, JSON.stringify(field.value), e.message
          );
        }
      }
      Logger.log('Updated task id=%s (%d field(s))', taskId, customFields.length);
    },

    /** Set a single custom field value via the dedicated endpoint. */
    setCustomField(taskId, fieldId, value) {
      _request('POST', '/task/' + taskId + '/field/' + fieldId, { value: value });
      Utilities.sleep(150);
      Logger.log('Set field %s on task %s', fieldId, taskId);
    },

    /** Permanently delete a task (used for SF orphans — reassigned opportunities). */
    deleteTask(taskId) {
      _request('DELETE', '/task/' + taskId);
      Logger.log('Deleted orphan task id=%s', taskId);
    },
  };

  // ----------------------------------------------------------------
  // Hydration helpers (private)
  // ----------------------------------------------------------------

  function _taskHasFieldValue(task, fieldId) {
    if (!fieldId) return false;
    for (const cf of (task.custom_fields || [])) {
      if (cf.id === fieldId) {
        const v = cf.value;
        return v !== null && v !== undefined && String(v).trim() !== '';
      }
    }
    return false;
  }

  /**
   * Some ClickUp list-task responses omit custom_fields or the SF ID field.
   * Hydrate those tasks individually so matching works correctly.
   */
  function _hydrateTasks(tasks, sfIdFieldId) {
    const needsHydration = tasks.filter(t => {
      if (!Array.isArray(t.custom_fields)) return true;
      if (sfIdFieldId && !_taskHasFieldValue(t, sfIdFieldId)) return true;
      return false;
    });

    if (needsHydration.length === 0) return tasks;

    Logger.log('%d task(s) missing custom field data — hydrating...', needsHydration.length);

    const hydratedById = {};
    for (const task of needsHydration) {
      if (!task.id) continue;
      try {
        hydratedById[task.id] = client.getTask(task.id);
      } catch (e) {
        Logger.log('Could not hydrate task id=%s; using list payload. Error: %s', task.id, e.message);
      }
    }

    return tasks.map(t => hydratedById[t.id] || t);
  }

  return client;
}
