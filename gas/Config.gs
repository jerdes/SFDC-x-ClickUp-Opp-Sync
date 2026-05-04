// Config.gs — Load all settings from Script Properties.
//
// Equivalent to config/settings.py. Set these via:
//   Extensions → Apps Script → Project Settings → Script Properties
//
// Required properties:
//   CLICKUP_API_TOKEN
//   CLICKUP_LIST_ID
//   CLICKUP_FIELD_ID_SF_OPPORTUNITY_ID
//
// Optional properties (with defaults shown):
//   GMAIL_SUBJECT_PATTERN          — default: "Salesforce Opportunity"
//   GMAIL_ATTACHMENT_NAME_PATTERN  — default: ".csv"
//   CLICKUP_BASE_URL               — default: "https://api.clickup.com/api/v2"
//   CLICKUP_FIELD_ID_<SUFFIX>      — one per field (see FIELD_REGISTRY below)
//   CSV_MAP_<CANONICAL_UPPER>      — override default CSV column headers

const FIELD_REGISTRY = [
  ['sf_opportunity_id',             'SF_OPPORTUNITY_ID'],
  ['account_name',                  'ACCOUNT_NAME'],
  ['stage',                         'STAGE'],
  ['sales_estimated_quota_relief',  'SALES_ESTIMATED_QUOTA_RELIEF'],
  ['close_date',                    'CLOSE_DATE'],
  ['next_step_date',                'NEXT_STEP_DATE'],
  ['next_step',                     'NEXT_STEP'],
  ['forecast_category',             'FORECAST_CATEGORY'],
  ['metrics',                       'METRICS'],
  ['economic_buyer',                'ECONOMIC_BUYER'],
  ['decision_criteria',             'DECISION_CRITERIA'],
  ['decision_process',              'DECISION_PROCESS'],
  ['paper_process',                 'PAPER_PROCESS'],
  ['implicated_pain',               'IMPLICATED_PAIN'],
  ['champion_name',                 'CHAMPION_NAME'],
  ['competitor',                    'COMPETITOR'],
  ['other_competitor',              'OTHER_COMPETITOR'],
  ['cuo_meeting_completed',         'CUO_MEETING_COMPLETED'],
  ['evaluation_agreed',             'EVALUATION_AGREED'],
  ['pricing_discussed',             'PRICING_DISCUSSED'],
  ['decision_criteria_met',         'DECISION_CRITERIA_MET'],
  ['economic_buyer_approved',       'ECONOMIC_BUYER_APPROVED'],
  ['ironclad_signatory',            'IRONCLAD_SIGNATORY'],
  ['map_url',                       'MAP_URL'],
  ['three_whys',                    'THREE_WHYS'],
  ['created_date',                  'CREATED_DATE'],
];

const CSV_HEADER_DEFAULTS = {
  sf_opportunity_id:            'Opportunity ID',
  name:                         'Opportunity Name',
  account_name:                 'Account Name',
  stage:                        'Stage',
  sales_estimated_quota_relief: 'Sales Estimated Quota Relief',
  close_date:                   'Close Date',
  next_step_date:               'Next Step Date',
  next_step:                    'Next Step',
  forecast_category:            'Forecast Category',
  metrics:                      'Metrics',
  economic_buyer:               'Economic Buyer',
  decision_criteria:            'Decision Criteria',
  decision_process:             'Decision Process',
  paper_process:                'Paper Process',
  implicated_pain:              'Implicated Pain',
  champion_name:                'Champion Name',
  competitor:                   'Competitor',
  other_competitor:             'Other Competitor',
  cuo_meeting_completed:        'CUO Meeting Completed',
  evaluation_agreed:            'Evaluation Agreed',
  pricing_discussed:            'Pricing Discussed',
  decision_criteria_met:        'Decision Criteria Met',
  economic_buyer_approved:      'Economic Buyer Approved',
  ironclad_signatory:           'Ironclad Signatory',
  map_url:                      'Mutual Action Plan (MAP) URL',
  three_whys:                   '3 Whys Business Case',
  created_date:                 'Created Date',
};

function loadSettings() {
  const props = PropertiesService.getScriptProperties().getProperties();

  function require(key) {
    const v = (props[key] || '').trim();
    if (!v) throw new Error('Missing required Script Property: ' + key);
    return v;
  }

  function optional(key, defaultVal) {
    return (props[key] || defaultVal || '').trim();
  }

  // CSV field map: canonical -> CSV column header (overrideable via CSV_MAP_*)
  const csvFieldMap = {};
  for (const [canonical, defaultHeader] of Object.entries(CSV_HEADER_DEFAULTS)) {
    const key = 'CSV_MAP_' + canonical.toUpperCase();
    csvFieldMap[canonical] = props[key] || defaultHeader;
  }

  // ClickUp field IDs: canonical -> ClickUp custom field UUID
  const clickupFieldIds = {};
  for (const [canonical, suffix] of FIELD_REGISTRY) {
    const key = 'CLICKUP_FIELD_ID_' + suffix;
    const v = (props[key] || '').trim();
    if (v) clickupFieldIds[canonical] = v;
  }

  return {
    gmailSubjectPattern:        optional('GMAIL_SUBJECT_PATTERN', 'Salesforce Opportunity'),
    gmailAttachmentNamePattern: optional('GMAIL_ATTACHMENT_NAME_PATTERN', '.csv'),
    clickupApiToken:            require('CLICKUP_API_TOKEN'),
    clickupListId:              require('CLICKUP_LIST_ID'),
    clickupBaseUrl:             optional('CLICKUP_BASE_URL', 'https://api.clickup.com/api/v2'),
    sheetsId:                   require('SHEETS_ID'),
    sheetsTabName:              optional('SHEETS_TAB_NAME', ''),
    clickupFieldIds:            clickupFieldIds,
    csvFieldMap:                csvFieldMap,
  };
}
