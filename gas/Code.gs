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
//        SHEETS_ID                          — Google Sheets spreadsheet ID (from URL)
//
//      OPTIONAL:
//        SHEETS_TAB_NAME                    — sheet tab name (defaults to first tab)
//        GMAIL_SUBJECT_PATTERN              — default: "Salesforce Opportunity"
//        GMAIL_ATTACHMENT_NAME_PATTERN      — default: ".csv"
//        CLICKUP_BASE_URL                   — default: "https://api.clickup.com/api/v2"
//        CLICKUP_FIELD_ID_<SUFFIX>          — one per field (see Config.gs for the full list)
//        CSV_MAP_<CANONICAL_UPPER>          — override default column headers
//
// 3. Authorise the script:
//      Run runSyncFromSheet() once manually → Google will prompt for Sheets + network permissions.
//
// 4. Install the polling trigger:
//      Run setupSheetPollingTrigger() once. This schedules runSyncIfSheetUpdated() to fire
//      every 15 minutes. The sync only actually runs when the Sheet has been modified since
//      the last run — if nothing changed the execution exits immediately.
//
// ════════════════════════════════════════════════════════════════════════════
// OPERATIONS (Google Sheets path — primary)
// ════════════════════════════════════════════════════════════════════════════
//
// - runSyncFromSheet()         — manual sync from Sheet (always runs regardless of changes)
// - runSyncIfSheetUpdated()    — polling trigger: only syncs when Sheet has been modified
// - setupSheetPollingTrigger() — run once to install the 15-min Sheet trigger
//
// ════════════════════════════════════════════════════════════════════════════
// OPERATIONS (Gmail/CSV path — legacy, kept for backward compatibility)
// ════════════════════════════════════════════════════════════════════════════
//
// - runSync()               — manual sync from latest Gmail attachment
// - runSyncIfNewReport()    — polling trigger: only syncs when a new email arrives
// - setupPollingTrigger()   — run once to install the 15-min Gmail trigger
//
// ════════════════════════════════════════════════════════════════════════════

// ────────────────────────────────────────────────────────────────────────────
// Google Sheets entry points (primary)
// ────────────────────────────────────────────────────────────────────────────

/**
 * Manual entry point. Runs the full Salesforce → ClickUp sync against the
 * Google Sheet, regardless of whether it was already processed.
 * Use this for testing or ad-hoc re-runs from the script editor.
 */
function runSyncFromSheet() {
  Logger.log('=== Salesforce → ClickUp sync starting (manual, Sheet) ===');

  let settings;
  try {
    settings = loadSettings();
  } catch (e) {
    Logger.log('FATAL: Configuration error: ' + e.message);
    throw e;
  }

  const sheetData = readOpportunitiesFromSheet(settings.sheetsId, settings.sheetsTabName);
  Logger.log('Parsing Sheet data...');
  _runSyncCore(parseSheetData(sheetData, settings.csvFieldMap), settings);
}

/**
 * Polling entry point — fires every 15 minutes via the trigger installed by
 * setupSheetPollingTrigger(). Exits immediately if the Sheet has not been
 * modified since the last successful sync.
 */
function runSyncIfSheetUpdated() {
  const props = PropertiesService.getScriptProperties();

  let settings;
  try {
    settings = loadSettings();
  } catch (e) {
    Logger.log('FATAL: Configuration error: ' + e.message);
    throw e;
  }

  const lastModified = getSheetLastModified(settings.sheetsId);
  const lastSynced = props.getProperty('LAST_SYNCED_SHEET_MTIME');

  if (lastSynced && new Date(lastSynced) >= lastModified) {
    Logger.log('Sheet unchanged since last sync (%s) — skipping.', lastSynced);
    return;
  }

  Logger.log('=== Sheet updated (%s) — starting sync ===', lastModified.toISOString());
  const sheetData = readOpportunitiesFromSheet(settings.sheetsId, settings.sheetsTabName);
  _runSyncCore(parseSheetData(sheetData, settings.csvFieldMap), settings);

  // Mark the Sheet's modification time so subsequent polls skip it
  props.setProperty('LAST_SYNCED_SHEET_MTIME', lastModified.toISOString());
  Logger.log('Recorded LAST_SYNCED_SHEET_MTIME=%s', lastModified.toISOString());
}

// ────────────────────────────────────────────────────────────────────────────
// Shared sync core
// ────────────────────────────────────────────────────────────────────────────

/**
 * Core sync logic shared by all entry points.
 * Initialises the ClickUp client, fetches live dropdown maps, and runs the engine.
 *
 * @param {Array}  opportunities  Pre-parsed opportunity objects.
 * @param {object} settings       Loaded settings object from loadSettings().
 */
function _runSyncCore(opportunities, settings) {
  if (opportunities.length === 0) {
    Logger.log('No valid opportunities found. Nothing to sync.');
    return;
  }

  const token = settings.clickupApiToken;
  Logger.log('ClickUp token: length=%d, prefix="%s…"', token.length, token.slice(0, 4));
  Logger.log('ClickUp base URL: %s', settings.clickupBaseUrl);

  const client = makeClickUpClient(
    settings.clickupApiToken,
    settings.clickupListId,
    settings.clickupBaseUrl
  );
  client.validateToken();

  // Fetch live dropdown option maps from the ClickUp workspace
  const listFields = client.getListFields();
  const { dropdownMaps, textCanonicals } = buildDropdownMapsFromFields(
    listFields,
    settings.clickupFieldIds
  );

  const sfIdFieldId = settings.clickupFieldIds['sf_opportunity_id'] || '';

  const summary = executeSyncEngine(
    opportunities,
    client,
    sfIdFieldId,
    settings.clickupFieldIds,
    dropdownMaps,
    textCanonicals
  );

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

// ────────────────────────────────────────────────────────────────────────────
// Gmail / CSV entry points (legacy — kept for backward compatibility)
// ────────────────────────────────────────────────────────────────────────────

/**
 * Manual entry point. Runs the full Salesforce → ClickUp sync against the
 * latest report email, regardless of whether it was already processed.
 * Use this for testing or ad-hoc re-runs from the script editor.
 */
function runSync() {
  Logger.log('=== Salesforce → ClickUp sync starting (manual, Gmail) ===');

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
 * Thin wrapper: parse CSV text then hand off to the shared sync core.
 */
function _runSyncWithCsv(csvText, settings) {
  Logger.log('Parsing CSV...');
  _runSyncCore(parseCsv(csvText, settings.csvFieldMap), settings);
}

/**
 * Polling entry point — fires every 15 minutes via the trigger installed by
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
 * Install the every-15-minutes polling trigger for the Google Sheets path.
 * Run this ONCE from the script editor after initial setup.
 * runSyncIfSheetUpdated() will fire every 15 minutes but exits immediately
 * when the Sheet has not changed since the last sync.
 */
function setupSheetPollingTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'runSyncIfSheetUpdated')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('runSyncIfSheetUpdated')
    .timeBased()
    .everyMinutes(15)
    .create();
  Logger.log('Sheet polling trigger installed (every 15 min). Check Triggers (⏱) in the left sidebar.');
}

/**
 * Install the every-15-minutes polling trigger for the Gmail/CSV path (legacy).
 * Run this ONCE from the script editor after initial setup.
 */
function setupPollingTrigger() {
  _deleteExistingTriggers();
  ScriptApp.newTrigger('runSyncIfNewReport')
    .timeBased()
    .everyMinutes(15)
    .create();
  Logger.log('Polling trigger installed (every 15 min). Check Triggers (⏱) in the left sidebar.');
}

/** Remove all existing triggers for the sync functions. */
function _deleteExistingTriggers() {
  const TRIGGER_FUNCTIONS = new Set([
    'runSyncIfNewReport',
    'runSyncIfSheetUpdated',
    '_runSyncAndReschedule',
  ]);
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (TRIGGER_FUNCTIONS.has(trigger.getHandlerFunction())) {
      ScriptApp.deleteTrigger(trigger);
    }
  }
}
