// Sync.gs — CSV parser, opportunity matcher, and sync engine.
//
// Replaces sync/parser.py, sync/matcher.py, and sync/engine.py.

// ----------------------------------------------------------------
// CSV Parser
// ----------------------------------------------------------------

/**
 * Parse raw CSV text into a list of opportunity objects.
 * Uses Utilities.parseCsv() (GAS built-in) instead of Python's csv.DictReader.
 *
 * @param {string} csvText   Raw CSV text (UTF-8, BOM stripped automatically).
 * @param {Object} fieldMap  canonical → CSV column header mapping from settings.
 * @returns {Array} List of opportunity objects.
 */
function parseCsv(csvText, fieldMap) {
  // Invert the map: CSV header → canonical name
  const headerToCanonical = {};
  for (const [canonical, header] of Object.entries(fieldMap)) {
    headerToCanonical[header] = canonical;
  }

  // Strip BOM if present
  const text = csvText.replace(/^\uFEFF/, '');
  const rows = Utilities.parseCsv(text);

  if (!rows || rows.length < 2) {
    throw new Error('CSV appears to be empty — no data rows found.');
  }

  const headers = rows[0];
  const csvHeaders = new Set(headers);

  // Validate the SF Opportunity ID column is present — without it nothing can match
  const sfIdHeader = fieldMap['sf_opportunity_id'];
  if (!csvHeaders.has(sfIdHeader)) {
    throw new Error(
      'CRITICAL: The Opportunity ID column "' + sfIdHeader + '" was not found in the CSV. ' +
      'Every row will be skipped without it. ' +
      'Either add this column to your Salesforce report or set ' +
      'CSV_MAP_SF_OPPORTUNITY_ID in Script Properties. ' +
      'Columns actually in this CSV: ' + JSON.stringify(headers)
    );
  }

  // Warn about any other mapped columns not present in this CSV
  for (const [canonical, header] of Object.entries(fieldMap)) {
    if (canonical !== 'sf_opportunity_id' && !csvHeaders.has(header)) {
      Logger.log(
        'WARNING: Expected CSV column "%s" (mapped from "%s") not found in file — ' +
        'it will be left blank. Check CSV_MAP_%s in Script Properties.',
        header, canonical, canonical.toUpperCase()
      );
    }
  }

  const opportunities = [];
  let skipped = 0;

  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    // Skip blank rows
    if (row.length === 0 || (row.length === 1 && row[0] === '')) continue;

    // Build a canonical → value map for this row
    const canonicalRow = {};
    for (let j = 0; j < headers.length; j++) {
      const canonical = headerToCanonical[headers[j]];
      if (canonical) canonicalRow[canonical] = (row[j] || '').trim();
    }

    const sfId = (canonicalRow['sf_opportunity_id'] || '').trim();
    if (!sfId) {
      Logger.log('Row %d skipped: missing Opportunity ID.', i + 1);
      skipped++;
      continue;
    }

    let name = (canonicalRow['name'] || '').trim();
    if (!name) {
      Logger.log('Row %d (id=%s) has no Opportunity Name — using ID as name.', i + 1, sfId);
      name = sfId;
    }

    opportunities.push({
      sf_opportunity_id:            sfId,
      name:                         name,
      account_name:                 canonicalRow['account_name']                 || '',
      stage:                        canonicalRow['stage']                        || '',
      sales_estimated_quota_relief: canonicalRow['sales_estimated_quota_relief'] || '',
      close_date:                   canonicalRow['close_date']                   || '',
      next_step_date:               canonicalRow['next_step_date']               || '',
      next_step:                    canonicalRow['next_step']                    || '',
      forecast_category:            canonicalRow['forecast_category']            || '',
      metrics:                      canonicalRow['metrics']                      || '',
      economic_buyer:               canonicalRow['economic_buyer']               || '',
      decision_criteria:            canonicalRow['decision_criteria']            || '',
      decision_process:             canonicalRow['decision_process']             || '',
      paper_process:                canonicalRow['paper_process']                || '',
      implicated_pain:              canonicalRow['implicated_pain']              || '',
      champion_name:                canonicalRow['champion_name']                || '',
      competitor:                   canonicalRow['competitor']                   || '',
      other_competitor:             canonicalRow['other_competitor']             || '',
      cuo_meeting_completed:        canonicalRow['cuo_meeting_completed']        || '',
      evaluation_agreed:            canonicalRow['evaluation_agreed']            || '',
      pricing_discussed:            canonicalRow['pricing_discussed']            || '',
      decision_criteria_met:        canonicalRow['decision_criteria_met']        || '',
      economic_buyer_approved:      canonicalRow['economic_buyer_approved']      || '',
      ironclad_signatory:           canonicalRow['ironclad_signatory']           || '',
      map_url:                      canonicalRow['map_url']                      || '',
      three_whys:                   canonicalRow['three_whys']                   || '',
      created_date:                 canonicalRow['created_date']                 || '',
    });
  }

  Logger.log('CSV parsed: %d opportunities loaded, %d rows skipped.', opportunities.length, skipped);
  return opportunities;
}

// ----------------------------------------------------------------
// Matcher
// ----------------------------------------------------------------

/**
 * Categorise opportunities and ClickUp tasks into three buckets.
 * Equivalent to match_opportunities() in sync/matcher.py.
 *
 * @returns {{ toCreate: Array, toUpdate: Array, toCloseOrphans: Array }}
 */
function matchOpportunities(opportunities, clickupTasks, sfIdFieldId) {
  if (!sfIdFieldId) {
    throw new Error(
      'CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID is not set. This field is required for matching.'
    );
  }

  // Build index: sf_opportunity_id → first ClickUp task with that ID
  const taskIndex = {};
  for (const task of clickupTasks) {
    const sfId = getCustomFieldValue(task, sfIdFieldId);
    if (!sfId) continue;
    const key = sfId.trim();
    if (taskIndex[key]) {
      Logger.log(
        'WARNING: Duplicate ClickUp tasks for SF ID "%s": keeping task id=%s, ignoring task id=%s. ' +
        'Remove the duplicate manually.',
        key, taskIndex[key].id, task.id
      );
    } else {
      taskIndex[key] = task;
    }
  }

  Logger.log(
    'Task index: %d of %d ClickUp tasks have a Salesforce Opportunity ID.',
    Object.keys(taskIndex).length, clickupTasks.length
  );

  if (clickupTasks.length > 0 && Object.keys(taskIndex).length === 0) {
    Logger.log(
      'WARNING: Fetched %d ClickUp tasks but NONE have the SF Opportunity ID field set ' +
      '(field_id=%s). All CSV rows will be treated as new creates. ' +
      'Check that CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID is correct.',
      clickupTasks.length, sfIdFieldId
    );
  }

  const toCreate = [];
  const toUpdate = [];
  const csvSfIds = new Set();

  for (const opp of opportunities) {
    csvSfIds.add(opp.sf_opportunity_id);
    const existing = taskIndex[opp.sf_opportunity_id];
    if (!existing) {
      toCreate.push(opp);
    } else {
      toUpdate.push([opp, existing]);
    }
  }

  // ClickUp tasks whose SF ID is absent from the CSV → orphans to close
  const toCloseOrphans = [];
  for (const [sfId, task] of Object.entries(taskIndex)) {
    if (!csvSfIds.has(sfId)) toCloseOrphans.push(task);
  }

  Logger.log(
    'Match result: %d to create, %d to update, %d orphans to close.',
    toCreate.length, toUpdate.length, toCloseOrphans.length
  );

  return { toCreate, toUpdate, toCloseOrphans };
}

// ----------------------------------------------------------------
// Sync engine
// ----------------------------------------------------------------

/**
 * Main sync loop: create / update / close.
 * Equivalent to run_sync() in sync/engine.py.
 *
 * A per-record try/catch ensures one bad record never aborts the entire run.
 *
 * @returns {{ created, updated, closed, skipped, errors }}
 */
function executeSyncEngine(opportunities, client, sfIdFieldId, fieldIds, dropdownMaps, textCanonicals) {
  const CLOSED_STATUS = 'DONE';
  const summary = { created: 0, updated: 0, closed: 0, skipped: 0, errors: [] };

  Logger.log('Fetching all ClickUp tasks...');
  const allTasks = client.getAllTasks(sfIdFieldId);
  const { toCreate, toUpdate, toCloseOrphans } = matchOpportunities(opportunities, allTasks, sfIdFieldId);

  // --- Create ---
  for (const opp of toCreate) {
    try {
      const customFields = buildCustomFieldsPayload(opp, fieldIds, dropdownMaps, textCanonicals);
      const task = client.createTask(opp.name);

      // Set non-critical fields individually. A bad field ID (e.g. wrong staging UUID)
      // logs a warning but does not abort the create — the task still lands in ClickUp.
      for (const field of customFields) {
        if (field.id === sfIdFieldId) continue; // handled explicitly below
        try {
          client.setCustomField(task.id, field.id, field.value);
        } catch (e) {
          Logger.log(
            'WARNING: Could not set field %s on new task %s: %s',
            field.id, task.id, e.message
          );
        }
      }

      // SF Opportunity ID must succeed — without it the task can't be matched on
      // future runs and will be treated as a new create, producing duplicates.
      if (sfIdFieldId) {
        client.setCustomField(task.id, sfIdFieldId, opp.sf_opportunity_id);
      }

      summary.created++;
      Logger.log('CREATED  "%s" (SF id=%s)', opp.name, opp.sf_opportunity_id);
    } catch (e) {
      const msg = 'Failed to CREATE "' + opp.name + '" (SF id=' + opp.sf_opportunity_id + '): ' + e.message;
      Logger.log('ERROR: ' + msg);
      summary.errors.push(msg);
    }
  }

  // --- Update (only changed fields) ---
  for (const [opp, task] of toUpdate) {
    const taskId = task.id;
    try {
      const changedFields = getChangedFieldsPayload(opp, task, fieldIds, dropdownMaps, textCanonicals);
      const nameChanged = opp.name !== (task.name || '');

      if (changedFields.length === 0 && !nameChanged) {
        summary.skipped++;
        Logger.log(
          'SKIPPED  "%s" (SF id=%s, CU id=%s) — no changes',
          opp.name, opp.sf_opportunity_id, taskId
        );
        continue;
      }

      client.updateTask(taskId, opp.name, changedFields);
      summary.updated++;
      Logger.log(
        'UPDATED  "%s" (SF id=%s, CU id=%s) — %d field(s) changed%s',
        opp.name, opp.sf_opportunity_id, taskId,
        changedFields.length, nameChanged ? ', name changed' : ''
      );
    } catch (e) {
      const msg = (
        'Failed to UPDATE "' + opp.name + '" ' +
        '(SF id=' + opp.sf_opportunity_id + ', CU id=' + taskId + '): ' + e.message
      );
      Logger.log('ERROR: ' + msg);
      summary.errors.push(msg);
    }
  }

  // --- Close orphans (ClickUp tasks whose SF ID is absent from the CSV) ---
  for (const task of toCloseOrphans) {
    const taskId = task.id;
    const taskName = task.name || taskId;
    try {
      client.closeOrphanTask(taskId, CLOSED_STATUS);
      summary.closed++;
      Logger.log('CLOSED   "%s" (CU id=%s) — SF ID not in CSV', taskName, taskId);
    } catch (e) {
      const msg = 'Failed to CLOSE orphan "' + taskName + '" (CU id=' + taskId + '): ' + e.message;
      Logger.log('ERROR: ' + msg);
      summary.errors.push(msg);
    }
  }

  Logger.log(
    'Sync complete. created=%d updated=%d closed=%d skipped=%d errors=%d',
    summary.created, summary.updated, summary.closed, summary.skipped, summary.errors.length
  );

  return summary;
}
