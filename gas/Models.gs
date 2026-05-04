// Models.gs — Field type conversions, dropdown maps, and custom-field payload builders.
//
// Replaces clickup/models.py. All logic is a direct port; comments explain any GAS differences.

// ----------------------------------------------------------------
// Field type sets
// ----------------------------------------------------------------

const _DATE_FIELDS = new Set(['close_date', 'next_step_date', 'created_date']);
const _NUMBER_FIELDS = new Set(['sales_estimated_quota_relief']);
const _URL_FIELDS = new Set(['map_url', 'three_whys']);
const _CHECKBOX_FIELDS = new Set([
  'cuo_meeting_completed',
  'evaluation_agreed',
  'pricing_discussed',
  'decision_criteria_met',
  'economic_buyer_approved',
]);

// ----------------------------------------------------------------
// Dropdown value maps (CSV display value → ClickUp option name)
// ----------------------------------------------------------------

const _STAGE_CSV_TO_CLICKUP = {
  '0 - pre-acceptance':        '0 - pre acceptance',
  '1 - initial interest':      '1 - initial interest',
  '2 - investigate & educate': '2 - investigate & educate',
  '3 - validate & justify':    '3 - validate & justify',
  '4 - paper process':         '4 & 5 - paper process & closing',
  '5 - closing':               '4 & 5 - paper process & closing',
  '6 - closed won':            '6 - closed won',
  '7 - closed lost':           'closed lost',
};

const _FORECAST_CATEGORY_CSV_TO_CLICKUP = {
  'best case':  'best case',
  'likely':     'likely',
  'commit':     'commit',
  'closed lost': 'closed lost',
  'closed won':  'closed won',
  'omitted':    'omitted',
};

const _DROPDOWN_CSV_MAPS = {
  stage:             _STAGE_CSV_TO_CLICKUP,
  forecast_category: _FORECAST_CATEGORY_CSV_TO_CLICKUP,
};

// ----------------------------------------------------------------
// Type conversion helpers
// ----------------------------------------------------------------

/**
 * Convert a DD/MM/YYYY date string to Unix timestamp in milliseconds (required by ClickUp).
 * Returns null if parsing fails.
 */
function _toTimestampMs(dateStr) {
  const parts = (dateStr || '').trim().split('/');
  if (parts.length !== 3) {
    Logger.log('Could not parse date "%s" (expected DD/MM/YYYY) — skipping field.', dateStr);
    return null;
  }
  const [dd, mm, yyyy] = parts;
  const d = new Date(Date.UTC(parseInt(yyyy, 10), parseInt(mm, 10) - 1, parseInt(dd, 10)));
  if (isNaN(d.getTime())) {
    Logger.log('Could not parse date "%s" (expected DD/MM/YYYY) — skipping field.', dateStr);
    return null;
  }
  return d.getTime();
}

/**
 * Convert a currency/number string to a float.
 * Strips leading $, commas, whitespace. Returns null on failure.
 */
function _toNumber(valueStr) {
  const clean = (valueStr || '').replace(/[$,\s]/g, '');
  const n = parseFloat(clean);
  if (isNaN(n)) {
    Logger.log('Could not parse number "%s" — skipping field.', valueStr);
    return null;
  }
  return n;
}

function _isValidUrl(value) {
  return value.startsWith('http://') || value.startsWith('https://');
}

// ----------------------------------------------------------------
// Dropdown map builder
// ----------------------------------------------------------------

/**
 * Build CSV-value → orderindex maps for dropdown fields by reading the actual
 * options from GET /list/{id}/field.  Equivalent to build_dropdown_maps_from_fields().
 *
 * @param {Array}  listFields  Raw field dicts from client.getListFields().
 * @param {Object} fieldIds    canonical → ClickUp field UUID mapping from settings.
 * @returns {{ dropdownMaps: Object, textCanonicals: Set }}
 */
function buildDropdownMapsFromFields(listFields, fieldIds) {
  const DROPDOWN_TYPES = new Set(['drop_down', 'dropdown', 'labels']);
  const TEXT_TYPES     = new Set(['short_text', 'text', 'url', 'email']);
  const DROPDOWN_CANONICALS = new Set(Object.keys(_DROPDOWN_CSV_MAPS));

  // Build UUID → canonical lookup for the dropdown fields we care about
  const uuidToCanonical = {};
  for (const canon of DROPDOWN_CANONICALS) {
    if (fieldIds[canon]) uuidToCanonical[fieldIds[canon]] = canon;
  }

  const dropdownMaps = {};
  const textCanonicals = new Set();

  for (const field of listFields) {
    const canonical = uuidToCanonical[field.id];
    if (!canonical) continue;

    if (TEXT_TYPES.has(field.type)) {
      Logger.log(
        'Field "%s" (id=%s) → canonical "%s" is type "%s" — will write as plain text.',
        field.name, field.id, canonical, field.type
      );
      textCanonicals.add(canonical);
      continue;
    }

    if (!DROPDOWN_TYPES.has(field.type)) {
      Logger.log(
        'WARNING: Field "%s" (id=%s) → canonical "%s" has unrecognised type "%s" — skipping.',
        field.name, field.id, canonical, field.type
      );
      continue;
    }

    const options = ((field.type_config || {}).options) || [];
    const nameToOrderindex = {};
    for (const opt of options) {
      if (opt.name != null && opt.orderindex != null) {
        nameToOrderindex[opt.name.toLowerCase().trim()] = parseInt(opt.orderindex, 10);
      }
    }
    dropdownMaps[canonical] = nameToOrderindex;
    Logger.log(
      'Dropdown "%s": loaded %d option(s): %s',
      canonical, Object.keys(nameToOrderindex).length, JSON.stringify(Object.keys(nameToOrderindex))
    );
  }

  for (const canon of DROPDOWN_CANONICALS) {
    if (!dropdownMaps[canon] && !textCanonicals.has(canon)) {
      Logger.log(
        'WARNING: Dropdown "%s": could not load options from ClickUp API — ' +
        'check that CLICKUP_FIELD_ID_%s is set and points to a dropdown field.',
        canon, canon.toUpperCase()
      );
    }
  }

  return { dropdownMaps, textCanonicals };
}

// ----------------------------------------------------------------
// Custom field value extraction
// ----------------------------------------------------------------

/**
 * Extract the string value of a custom field from a ClickUp task dict.
 * Returns null if not found or not set.
 */
function getCustomFieldValue(task, fieldId) {
  for (const cf of (task.custom_fields || [])) {
    if (cf.id === fieldId) {
      const v = cf.value;
      if (v === null || v === undefined) return null;
      return String(v);
    }
  }
  return null;
}

// ----------------------------------------------------------------
// Payload builders
// ----------------------------------------------------------------

/**
 * Build the custom_fields array for a ClickUp create/update request.
 * Equivalent to build_custom_fields_payload() in clickup/models.py.
 */
function buildCustomFieldsPayload(opp, fieldIds, dropdownMaps, textCanonicals) {
  const fieldValues = {
    sf_opportunity_id:            opp.sf_opportunity_id,
    account_name:                 opp.account_name,
    stage:                        opp.stage,
    sales_estimated_quota_relief: opp.sales_estimated_quota_relief,
    close_date:                   opp.close_date,
    next_step_date:               opp.next_step_date,
    next_step:                    opp.next_step,
    forecast_category:            opp.forecast_category,
    metrics:                      opp.metrics,
    economic_buyer:               opp.economic_buyer,
    decision_criteria:            opp.decision_criteria,
    decision_process:             opp.decision_process,
    paper_process:                opp.paper_process,
    implicated_pain:              opp.implicated_pain,
    champion_name:                opp.champion_name,
    competitor:                   opp.competitor,
    other_competitor:             opp.other_competitor,
    cuo_meeting_completed:        opp.cuo_meeting_completed,
    evaluation_agreed:            opp.evaluation_agreed,
    pricing_discussed:            opp.pricing_discussed,
    decision_criteria_met:        opp.decision_criteria_met,
    economic_buyer_approved:      opp.economic_buyer_approved,
    ironclad_signatory:           opp.ironclad_signatory,
    map_url:                      opp.map_url,
    three_whys:                   opp.three_whys,
    created_date:                 opp.created_date,
  };

  const payload = [];

  for (const [canonical, value] of Object.entries(fieldValues)) {
    const fieldId = fieldIds[canonical];
    if (!fieldId) continue;

    if (_CHECKBOX_FIELDS.has(canonical)) {
      if (!(value || '').trim()) continue;
      const v = value.trim().toLowerCase();
      payload.push({ id: fieldId, value: v === '1' || v === 'true' });

    } else if (_DATE_FIELDS.has(canonical)) {
      if (value) {
        const ts = _toTimestampMs(value);
        if (ts !== null) payload.push({ id: fieldId, value: ts });
      }

    } else if (_NUMBER_FIELDS.has(canonical)) {
      if (value) {
        const num = _toNumber(value);
        if (num !== null) payload.push({ id: fieldId, value: num });
      }

    } else if (_URL_FIELDS.has(canonical)) {
      if (value) {
        if (_isValidUrl(value)) {
          payload.push({ id: fieldId, value: value });
        } else {
          Logger.log(
            'Skipping "%s" for field "%s" — not a valid URL (must start with http/https).',
            value, canonical
          );
        }
      }

    } else if (_DROPDOWN_CSV_MAPS[canonical]) {
      if (value) {
        if (textCanonicals && textCanonicals.has(canonical)) {
          // The configured ClickUp field is plain text — write directly
          payload.push({ id: fieldId, value: value.trim() });
        } else {
          // Dropdown: CSV value → ClickUp option name → orderindex
          const csvKey = value.trim().toLowerCase();
          const clickupName = _DROPDOWN_CSV_MAPS[canonical][csvKey];
          if (clickupName == null) {
            Logger.log(
              'WARNING: No mapping for %s CSV value "%s" — skipping. Known CSV values: %s',
              canonical, value, JSON.stringify(Object.keys(_DROPDOWN_CSV_MAPS[canonical]))
            );
          } else if (dropdownMaps && dropdownMaps[canonical]) {
            const orderindex = dropdownMaps[canonical][clickupName.toLowerCase()];
            if (orderindex !== undefined) {
              payload.push({ id: fieldId, value: orderindex });
            } else {
              Logger.log(
                'WARNING: CSV value "%s" maps to ClickUp option "%s" but that option was not ' +
                'found in live options for "%s". Known ClickUp options: %s',
                value, clickupName, canonical, JSON.stringify(Object.keys(dropdownMaps[canonical]))
              );
            }
          } else {
            Logger.log(
              'WARNING: No live dropdown options loaded for "%s" (value="%s") — skipping.',
              canonical, value
            );
          }
        }
      }

    } else {
      // Plain text / short_text — pass as-is
      if (value) payload.push({ id: fieldId, value: value });
    }
  }

  return payload;
}

/**
 * Compare a target value (already converted from CSV) with the current ClickUp API value.
 * Returns true when they represent identical data. Equivalent to _values_equal().
 */
function _valuesEqual(target, current) {
  // Checkbox: ClickUp returns null for unchecked, which equals false — check before the null guard
  if (typeof target === 'boolean') {
    if (current === null || current === undefined) return target === false;
    if (typeof current === 'boolean') return target === current;
    return target === (['true', '1', 'yes'].includes(String(current).toLowerCase()));
  }

  if (current === null || current === undefined || current === '') return false;

  // Date (int ms) or number (float) — compare numerically
  if (typeof target === 'number') {
    const c = parseFloat(current);
    if (isNaN(c)) return false;
    // Date timestamps are large ms-since-epoch values. ClickUp stores dates as midnight
    // in the workspace timezone, so the stored ms can differ from our midnight-UTC value
    // by several hours. Compare at day granularity (round to nearest day) to absorb the
    // timezone offset. Regular numbers (currency etc.) are small enough that rounding
    // to the nearest day would be wrong, so use tolerance < 1 for those instead.
    if (target > 1e11) {
      return Math.round(target / 86400000) === Math.round(c / 86400000);
    }
    return Math.abs(target - c) < 1;
  }

  // Text / url — plain string comparison
  return String(target).trim() === String(current).trim();
}

/**
 * Return only the custom_fields payload entries whose value differs from
 * what is currently stored in the ClickUp task.
 * Equivalent to get_changed_fields_payload() in clickup/models.py.
 */
function getChangedFieldsPayload(opp, existingTask, fieldIds, dropdownMaps, textCanonicals) {
  const targetPayload = buildCustomFieldsPayload(opp, fieldIds, dropdownMaps, textCanonicals);

  const currentById = {};
  for (const cf of (existingTask.custom_fields || [])) {
    currentById[cf.id] = (cf.value !== undefined) ? cf.value : null;
  }

  return targetPayload.filter(item => !_valuesEqual(item.value, currentById[item.id]));
}
