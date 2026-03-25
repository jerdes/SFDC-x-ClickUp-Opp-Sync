// Code.gs — Entry point for the Salesforce → ClickUp sync (Google Apps Script version).
//
// ════════════════════════════════════════════════════════════════════════════
// SETUP (one-time)
// ════════════════════════════════════════════════════════════════════════════
//
// 1. Go to script.google.com and create a new project named e.g. "SFDC-ClickUp Sync".
//    (Or push these files with clasp: https://github.com/google/clasp)
//
// 2. Set the project timezone:
//      Project Settings (⚙) → Time zone → Australia/Sydney
//    This is required for the 9:03 AM Sydney trigger to fire at the right time.
//
// 3. Add Script Properties (Project Settings → Script Properties → Add):
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
// 4. Authorise the script:
//      Run runSync() once manually → Google will prompt for Gmail + network permissions.
//
// 5. Install the daily trigger:
//      Run setupDailyTrigger() once. This schedules runSync() at 9:03 AM Sydney time
//      every day using a self-rescheduling one-time trigger (the only GAS mechanism
//      that guarantees a specific minute, not just a specific hour).
//
// ════════════════════════════════════════════════════════════════════════════
// DAILY OPERATIONS
// ════════════════════════════════════════════════════════════════════════════
//
// - The trigger fires automatically at 9:03 AM Sydney time and reschedules itself.
// - To run manually: open the script editor → select runSync → ▶ Run.
// - Execution logs: View → Logs (or Executions in the left sidebar).
//
// ════════════════════════════════════════════════════════════════════════════

/**
 * Main entry point. Runs the full Salesforce → ClickUp sync.
 * Safe to run manually at any time.
 */
function runSync() {
  Logger.log('=== Salesforce → ClickUp sync starting ===');

  // 1. Load settings from Script Properties
  let settings;
  try {
    settings = loadSettings();
  } catch (e) {
    Logger.log('FATAL: Configuration error: ' + e.message);
    throw e;
  }

  // 2. Fetch the latest CSV attachment from Gmail
  Logger.log(
    'Connecting to Gmail as script owner, searching for subject="%s"...',
    settings.gmailSubjectPattern
  );
  const csvText = fetchLatestCsvAttachment(
    settings.gmailSubjectPattern,
    settings.gmailAttachmentNamePattern
  );

  // 3. Parse the CSV
  Logger.log('Parsing CSV...');
  const opportunities = parseCsv(csvText, settings.csvFieldMap);

  if (opportunities.length === 0) {
    Logger.log('No valid opportunities found in CSV. Nothing to sync.');
    return;
  }

  // 4. Initialise the ClickUp client and validate the token
  const token = settings.clickupApiToken;
  Logger.log('ClickUp token: length=%d, prefix="%s…"', token.length, token.slice(0, 4));
  Logger.log('ClickUp base URL: %s', settings.clickupBaseUrl);

  const client = makeClickUpClient(
    settings.clickupApiToken,
    settings.clickupListId,
    settings.clickupBaseUrl
  );
  client.validateToken();

  // 5. Fetch live dropdown option maps from the ClickUp workspace
  const listFields = client.getListFields();
  const { dropdownMaps, textCanonicals } = buildDropdownMapsFromFields(
    listFields,
    settings.clickupFieldIds
  );

  const sfIdFieldId = settings.clickupFieldIds['sf_opportunity_id'] || '';

  // 6. Run the sync
  const summary = executeSyncEngine(
    opportunities,
    client,
    sfIdFieldId,
    settings.clickupFieldIds,
    dropdownMaps,
    textCanonicals
  );

  // 7. Log final summary
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
// Trigger management
// ════════════════════════════════════════════════════════════════════════════

/**
 * Install the daily 9:03 AM Sydney trigger.
 * Run this ONCE from the script editor after initial setup.
 * It uses a self-rescheduling one-time trigger — the only GAS mechanism
 * that guarantees a specific minute (atHour-only triggers fire at a random
 * minute within the hour).
 */
function setupDailyTrigger() {
  _deleteExistingTriggers();
  _scheduleNextRun();
  Logger.log('Daily trigger installed. Check Triggers (⏱) in the left sidebar to confirm.');
}

/**
 * Wrapper called by the trigger. Runs the sync then reschedules for tomorrow.
 * Do NOT rename this function — the trigger is registered against this name.
 */
function _runSyncAndReschedule() {
  // Delete the one-time trigger that just fired (GAS does not auto-delete them)
  _deleteExistingTriggers();

  try {
    runSync();
  } finally {
    // Always reschedule, even if today's sync threw an error
    _scheduleNextRun();
  }
}

/**
 * Schedule a one-time trigger for 9:03 AM Sydney time on the next calendar day
 * (or today, if it's currently before 9:03 AM).
 *
 * setHours() uses the project timezone (Australia/Sydney), so DST transitions
 * are handled automatically by GAS — no manual UTC arithmetic needed.
 */
function _scheduleNextRun() {
  const now = new Date();

  const target = new Date(now);
  target.setHours(9, 3, 0, 0);   // 09:03:00.000 in project timezone (Australia/Sydney)

  // If that time has already passed today, push to tomorrow
  if (target <= now) {
    target.setDate(target.getDate() + 1);
  }

  ScriptApp.newTrigger('_runSyncAndReschedule').timeBased().at(target).create();
  Logger.log('Next sync scheduled for: ' + target.toString());
}

/** Remove all existing triggers for the sync functions. */
function _deleteExistingTriggers() {
  const TRIGGER_FUNCTIONS = new Set(['_runSyncAndReschedule']);
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (TRIGGER_FUNCTIONS.has(trigger.getHandlerFunction())) {
      ScriptApp.deleteTrigger(trigger);
    }
  }
}
