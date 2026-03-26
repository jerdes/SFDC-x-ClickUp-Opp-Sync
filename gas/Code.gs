// Code.gs — Entry point for the Salesforce → ClickUp sync (Google Apps Script version).
//
// ════════════════════════════════════════════════════════════════════════════
// SETUP (one-time)
// ════════════════════════════════════════════════════════════════════════════
//
// 1. Go to script.google.com and create a new project named e.g. "SFDC-ClickUp Sync".
//    (Or push these files with clasp: https://github.com/google/clasp)
//
// 2. Add Script Properties (Project Settings → Script Properties → Add):
//
//      REQUIRED:
//        CLICKUP_API_TOKEN                  — your ClickUp API token
//        CLICKUP_LIST_ID                    — your ClickUp list ID
//        CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID — ClickUp custom field UUID for SF Opportunity ID
//
//      OPTIONAL (same defaults as the Python version):
//        GMAIL_SUBJECT_PATTERN              — default: "Salesforce Opportunity"
//        GMAIL_ATTACHMENT_NAME_PATTERN      — default: ".csv"
//        CLICKUP_BASE_URL                   — default: "https://api.clickup.com/api/v2"
//        CLICKUP_FIELD_ID_<SUFFIX>          — one per field (see Config.gs for the full list)
//        CSV_MAP_<CANONICAL_UPPER>          — override default CSV column headers
//
// 3. Authorise the script:
//      Run runSync() once manually → Google will prompt for Gmail + network permissions.
//
// 4. Install the polling trigger:
//      Run setupPollingTrigger() once. This schedules runSyncIfNewReport() to fire
//      every 5 minutes. The sync only actually runs when a new report email arrives —
//      if no new report is found the execution exits immediately.
//
// ════════════════════════════════════════════════════════════════════════════
// OPERATIONS
// ════════════════════════════════════════════════════════════════════════════
//
// - runSyncIfNewReport() fires every 5 minutes and processes a new report the moment
//   it lands in the inbox (within ~5 minutes). Works for any report frequency.
// - To run manually: open the script editor → select runSync → ▶ Run.
//   runSync() always processes the latest report regardless of whether it was
//   already processed (useful for testing / re-running).
// - Execution logs: View → Logs (or Executions in the left sidebar).
//
// ════════════════════════════════════════════════════════════════════════════

/**
 * Manual entry point. Runs the full Salesforce → ClickUp sync against the
 * latest report email, regardless of whether it was already processed.
 * Use this for testing or ad-hoc re-runs from the script editor.
 */
function runSync() {
  Logger.log('=== Salesforce → ClickUp sync starting (manual) ===');

  let settings;
  try {
    settings = loadSettings();
  } catch (e) {
    Logger.log('FATAL: Configuration error: ' + e.message);
    throw e;
  }

  Logger.log(
    'Connecting to Gmail as script owner, searching for subject="%s"...',
    settings.gmailSubjectPattern
  );
  const csvText = fetchLatestCsvAttachment(
    settings.gmailSubjectPattern,
    settings.gmailAttachmentNamePattern
  );

  _runSyncWithCsv(csvText, settings);
}

/**
 * Core sync logic shared by runSync() and runSyncIfNewReport().
 * Parses the CSV, initialises the ClickUp client, and runs the sync engine.
 *
 * @param {string} csvText   Raw CSV text from the Gmail attachment.
 * @param {object} settings  Loaded settings object from loadSettings().
 */
function _runSyncWithCsv(csvText, settings) {
  // 1. Parse the CSV
  Logger.log('Parsing CSV...');
  const opportunities = parseCsv(csvText, settings.csvFieldMap);

  if (opportunities.length === 0) {
    Logger.log('No valid opportunities found in CSV. Nothing to sync.');
    return;
  }

  // 2. Initialise the ClickUp client and validate the token
  const token = settings.clickupApiToken;
  Logger.log('ClickUp token: length=%d, prefix="%s…"', token.length, token.slice(0, 4));
  Logger.log('ClickUp base URL: %s', settings.clickupBaseUrl);

  const client = makeClickUpClient(
    settings.clickupApiToken,
    settings.clickupListId,
    settings.clickupBaseUrl
  );
  client.validateToken();

  // 3. Fetch live dropdown option maps from the ClickUp workspace
  const listFields = client.getListFields();
  const { dropdownMaps, textCanonicals } = buildDropdownMapsFromFields(
    listFields,
    settings.clickupFieldIds
  );

  const sfIdFieldId = settings.clickupFieldIds['sf_opportunity_id'] || '';

  // 4. Run the sync
  const summary = executeSyncEngine(
    opportunities,
    client,
    sfIdFieldId,
    settings.clickupFieldIds,
    dropdownMaps,
    textCanonicals
  );

  // 5. Log final summary
  Logger.log(
    '=== Sync finished: created=%d updated=%d closed=%d skipped=%d errors=%d ===',
    summary.created, summary.updated, summary.closed, summary.skipped, summary.errors.length
  );

  if (summary.errors.length > 0) {
    for (const err of summary.errors) {
      Logger.log('Error: ' + err);
    }
    throw new Error(
      'Sync completed with ' + summary.errors.length + ' error(s). See Executions log for details.'
    );
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Event-driven entry point (called by the polling trigger)
// ════════════════════════════════════════════════════════════════════════════

/**
 * Polling entry point — fires every 5 minutes via the trigger installed by
 * setupPollingTrigger(). Exits immediately if no new report email has arrived
 * since the last successful sync. Processes the report and records its
 * message ID in Script Properties so it is never processed twice.
 */
function runSyncIfNewReport() {
  const props = PropertiesService.getScriptProperties();
  const lastProcessedId = props.getProperty('LAST_PROCESSED_EMAIL_ID') || '';

  let settings;
  try {
    settings = loadSettings();
  } catch (e) {
    Logger.log('FATAL: Configuration error: ' + e.message);
    throw e;
  }

  const result = fetchLatestCsvIfNew(
    settings.gmailSubjectPattern,
    settings.gmailAttachmentNamePattern,
    lastProcessedId
  );

  if (!result) {
    // No new report — nothing to do.
    return;
  }

  Logger.log('=== New report detected (message id=%s) — starting sync ===', result.messageId);
  _runSyncWithCsv(result.csvText, settings);

  // Mark this email as processed so subsequent polls skip it.
  props.setProperty('LAST_PROCESSED_EMAIL_ID', result.messageId);
  Logger.log('Recorded LAST_PROCESSED_EMAIL_ID=%s', result.messageId);
}

// ════════════════════════════════════════════════════════════════════════════
// Trigger management
// ════════════════════════════════════════════════════════════════════════════

/**
 * Install the every-5-minutes polling trigger.
 * Run this ONCE from the script editor after initial setup.
 * runSyncIfNewReport() will fire every 5 minutes but exits immediately
 * when no new report is waiting — it only syncs when a fresh email arrives.
 */
function setupPollingTrigger() {
  _deleteExistingTriggers();
  ScriptApp.newTrigger('runSyncIfNewReport')
    .timeBased()
    .everyMinutes(5)
    .create();
  Logger.log('Polling trigger installed (every 5 min). Check Triggers (⏱) in the left sidebar.');
}

/** Remove all existing triggers for the sync functions. */
function _deleteExistingTriggers() {
  const TRIGGER_FUNCTIONS = new Set(['runSyncIfNewReport', '_runSyncAndReschedule']);
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (TRIGGER_FUNCTIONS.has(trigger.getHandlerFunction())) {
      ScriptApp.deleteTrigger(trigger);
    }
  }
}
