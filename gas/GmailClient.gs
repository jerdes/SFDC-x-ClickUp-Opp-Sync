// GmailClient.gs — Fetch the latest Salesforce CSV attachment via GmailApp.
//
// Replaces gmail/client.py. No App Password or IMAP config needed —
// GmailApp uses the OAuth identity of the script owner automatically.

/**
 * Search Gmail for the most recent email matching subjectPattern and return
 * the text content of its first attachment matching attachmentNamePattern.
 *
 * @param {string} subjectPattern        Substring to match in the email subject.
 * @param {string} attachmentNamePattern Suffix or glob (e.g. ".csv", "*.csv").
 * @returns {string} Raw text content of the matched CSV attachment.
 * @throws {Error} If no matching email or attachment is found.
 */
function fetchLatestCsvAttachment(subjectPattern, attachmentNamePattern) {
  Logger.log('Gmail: searching for emails with subject containing "%s"', subjectPattern);

  // GmailApp.search() returns threads newest-first by default
  const threads = GmailApp.search('subject:"' + subjectPattern + '" has:attachment', 0, 10);

  if (!threads || threads.length === 0) {
    throw new Error(
      'No emails found matching subject: "' + subjectPattern + '". ' +
      'Check GMAIL_SUBJECT_PATTERN in Script Properties.'
    );
  }

  // Work through threads from newest to oldest until we find a matching attachment
  for (const thread of threads) {
    const messages = thread.getMessages();
    // Most recent message in the thread
    const msg = messages[messages.length - 1];
    const attachments = msg.getAttachments();

    for (const att of attachments) {
      const filename = att.getName() || '';
      if (_attachmentMatchesPattern(filename, attachmentNamePattern)) {
        Logger.log(
          'Gmail: found attachment "%s" (%d bytes) in message from %s',
          filename, att.getSize(), msg.getDate()
        );
        return att.getDataAsString();
      }
    }
  }

  throw new Error(
    'No attachment matching "' + attachmentNamePattern + '" found in the most recent emails ' +
    'with subject "' + subjectPattern + '". ' +
    'Check GMAIL_ATTACHMENT_NAME_PATTERN in Script Properties.'
  );
}

/**
 * Returns true if filename matches the given pattern.
 * Supports plain suffixes (".csv") and simple globs ("*.csv").
 */
function _attachmentMatchesPattern(filename, pattern) {
  const f = filename.toLowerCase();
  const p = pattern.toLowerCase().replace(/^\*/, '');  // strip leading * from "*.csv" → ".csv"
  return f.endsWith(p);
}
