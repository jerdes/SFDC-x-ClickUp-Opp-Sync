// SheetsClient.gs — Read opportunity rows from a Google Sheet.
//
// Used when the Data Connector for Salesforce syncs Salesforce report data
// directly into a Google Sheet, replacing the Gmail/CSV attachment path.

/**
 * Read all rows from the configured Google Sheet.
 * Returns { headers: string[], rows: string[][] } using display values
 * (formatted strings, matching the existing date/number parsing expectations).
 *
 * @param {string} spreadsheetId  Spreadsheet ID from the sheet URL.
 * @param {string} tabName        Tab/sheet name; pass '' to use the first tab.
 * @returns {{ headers: string[], rows: string[][] }}
 */
function readOpportunitiesFromSheet(spreadsheetId, tabName) {
  const ss = SpreadsheetApp.openById(spreadsheetId);
  const sheet = tabName ? ss.getSheetByName(tabName) : ss.getSheets()[0];
  if (!sheet) {
    throw new Error(
      'Sheet tab "' + tabName + '" not found in spreadsheet ' + spreadsheetId +
      '. Available tabs: ' + ss.getSheets().map(s => s.getName()).join(', ')
    );
  }

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2) {
    throw new Error('Sheet "' + sheet.getName() + '" appears to be empty — no data rows found.');
  }

  const allValues = sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();
  Logger.log(
    'Sheet "%s": read %d data rows, %d columns.',
    sheet.getName(), lastRow - 1, lastCol
  );
  return { headers: allValues[0], rows: allValues.slice(1) };
}

/**
 * Return the last-modified Date of the spreadsheet file via Drive metadata.
 * Used for polling-based change detection in runSyncIfSheetUpdated().
 *
 * @param {string} spreadsheetId  Spreadsheet ID.
 * @returns {Date}
 */
function getSheetLastModified(spreadsheetId) {
  return DriveApp.getFileById(spreadsheetId).getLastUpdated();
}
