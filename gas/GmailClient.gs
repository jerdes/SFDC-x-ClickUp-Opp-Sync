// GmailClient.gs — Fetch the latest Salesforce CSV attachment via GmailApp.
//
// Replaces gmail/client.py. No App Password or IMAP config needed —
// GmailApp uses the OAuth identity of the script owner automatically.

/**
 * Search Gmail for the most recent email matching subjectPattern and return
 * the text content of its first attachment matching attachmentNamePattern,
 * along with the message ID — but ONLY if the message is newer than
 * lastProcessedMessageId.
 *
 * Returns null (does not throw) when:
 *   - No matching email exists
 *   - The most recent matching email has already been processed
 *
 * @param {string} subjectPattern        Substring to match in the email subject.
 * @param {string} attachmentNamePattern Suffix or glob (e.g. ".csv", "*.csv").
 * @param {string} lastProcessedId       Message ID already processed ('' for first run).
 * @returns {{ csvText: string, messageId: string }|null}
 */
function fetchLatestCsvIfNew(subjectPattern, attachmentNamePattern, lastProcessedId) {
  Logger.log('Gmail: searching for emails with subject containing "%s"', subjectPattern);

  // GmailApp.search() returns threads newest-first by default
  const threads = GmailApp.search('subject:"' + subjectPattern + '" has:attachment', 0, 10);

  if (!threads || threads.length === 0) {
    Logger.log('Gmail: no emails found matching subject "%s" — nothing to sync.', subjectPattern);
    return null;
  }

  // Work through threads from newest to oldest until we find a matching attachment
  for (const thread of threads) {
    const messages = thread.getMessages();
    // Most recent message in the thread first
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      const attachments = msg.getAttachments();

      for (const att of attachments) {
        const filename = att.getName() || '';
        if (!_attachmentMatchesPattern(filename, attachmentNamePattern)) continue;

        const messageId = msg.getId();

        if (messageId === lastProcessedId) {
          Logger.log(
            'Gmail: most recent report (message id=%s, date=%s) already processed — skipping.',
            messageId, msg.getDate()
          );
          return null;
        }

        Logger.log(
          'Gmail: new report found — attachment "%s" (%d bytes), message id=%s, date=%s',
          filename, att.getSize(), messageId, msg.getDate()
        );
        return { csvText: att.getDataAsString(), messageId: messageId };
      }
    }
  }

  Logger.log(
    'Gmail: no attachment matching "%s" found in recent emails with subject "%s" — nothing to sync.',
    attachmentNamePattern, subjectPattern
  );
  return null;
}

/**
 * Fetch the latest CSV attachment unconditionally (used for manual runSync() calls).
 * Throws if no matching email or attachment is found.
 *
 * @param {string} subjectPattern        Substring to match in the email subject.
 * @param {string} attachmentNamePattern Suffix or glob (e.g. ".csv", "*.csv").
 * @returns {string} Raw text content of the matched CSV attachment.
 */
function fetchLatestCsvAttachment(subjectPattern, attachmentNamePattern) {
  const result = fetchLatestCsvIfNew(subjectPattern, attachmentNamePattern, '');
  if (!result) {
    throw new Error(
      'No attachment matching "' + attachmentNamePattern + '" found in recent emails ' +
      'with subject "' + subjectPattern + '". ' +
      'Check GMAIL_SUBJECT_PATTERN and GMAIL_ATTACHMENT_NAME_PATTERN in Script Properties.'
    );
  }
  return result.csvText;
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
