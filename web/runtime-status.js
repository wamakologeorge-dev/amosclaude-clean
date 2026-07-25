/**
 * Amosclaud runtime status summary.
 *
 * Pure translation of the existing `/ready` payload — specifically
 * `provider.model_runtime`, produced by `amoscloud_ai/model_runtime.py` — into
 * honest operator text for the Command Center.
 *
 * Rules this module keeps:
 *  - it reuses the backend's stable diagnostic codes, it never invents new ones;
 *  - it renders the backend remediation, never the raw transport `detail`
 *    (which can carry an operating-system errno such as `[Errno -2]`);
 *  - it never claims a runtime is reachable unless the backend says so;
 *  - it never suggests an OpenAI or other external API key.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.AmosclaudRuntimeStatus = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Stable machine codes from amoscloud_ai/model_runtime.py. Do not rename.
  var CODE_HEADLINES = {
    dns_unresolved: 'Model hostname cannot be resolved from this deployment',
    connection_refused: 'Nothing is listening on the model endpoint',
    tls_error: 'TLS with the model endpoint could not be negotiated',
    timeout: 'The model endpoint did not answer in time',
    auth_rejected: 'The model endpoint rejected the Amosclaud credentials',
    model_not_found: 'The model endpoint does not serve the requested model',
    bad_response: 'The model endpoint returned a reply Amosclaud cannot use',
    unconfigured: 'No Amosclaud model runtime is configured',
  };

  var NATIVE_NOTE =
    'Native Amosclaud actions still work without a model runtime: create and ' +
    'list repositories, record and read issues, create branches, commit ' +
    'supplied files, and open native pull requests.';

  var NO_KEY_NOTE =
    'No OpenAI or other external API key is required. Amosclaud prefers ' +
    'first-party model routes, and external adapters stay off unless a server ' +
    'operator explicitly enables them.';

  function text(value) {
    return value === null || value === undefined ? '' : String(value);
  }

  function candidateList(runtime) {
    var raw = runtime && runtime.candidates;
    return Array.isArray(raw) ? raw : [];
  }

  function describeCandidate(entry) {
    return {
      key: text(entry.candidate),
      label: text(entry.label) || text(entry.candidate),
      kind: text(entry.kind),
      firstParty: text(entry.kind) !== 'external',
      configured: entry.configured === true,
      reachable: entry.reachable === true,
      code: text(entry.failure_code),
      remediation: text(entry.remediation),
    };
  }

  function activePath(reachable, preferredKey, described) {
    var preferred = described.filter(function (item) {
      return item.key === preferredKey;
    })[0];
    if (reachable && preferred) {
      return {
        label: preferred.label,
        key: preferred.key,
        firstParty: preferred.firstParty,
        state: preferred.firstParty
          ? 'First-party model route in use'
          : 'Operator-enabled external adapter in use',
      };
    }
    var configuredFirstParty = described.filter(function (item) {
      return item.firstParty && item.configured;
    })[0];
    if (configuredFirstParty) {
      return {
        label: configuredFirstParty.label,
        key: configuredFirstParty.key,
        firstParty: true,
        state: 'Configured first-party route, currently not reachable',
      };
    }
    return {
      label: 'No first-party model runtime is configured',
      key: '',
      firstParty: true,
      state: 'Configured first-party route, currently not reachable',
    };
  }

  /**
   * Summarize a `/ready` response body. Missing or malformed payloads are
   * reported as unknown rather than guessed at.
   */
  function summarize(ready) {
    var body = ready && typeof ready === 'object' ? ready : {};
    var provider = body.provider && typeof body.provider === 'object' ? body.provider : {};
    var runtime =
      provider.model_runtime && typeof provider.model_runtime === 'object'
        ? provider.model_runtime
        : null;
    if (!runtime) {
      return {
        known: false,
        reachable: false,
        status: 'unknown',
        headline: 'Runtime status is unavailable',
        code: '',
        remediation:
          'Amosclaud could not read its own readiness report. Reload the page, ' +
          'and check the server log if this persists.',
        activePath: 'Unknown',
        activePathState: '',
        candidates: [],
        externalAdaptersEnabled: false,
        nativeNote: NATIVE_NOTE,
        noKeyNote: NO_KEY_NOTE,
        message: 'Runtime status is unavailable. ' + NATIVE_NOTE,
      };
    }

    var described = candidateList(runtime).map(describeCandidate);
    var reachable = runtime.reachable === true;
    var active = activePath(reachable, text(runtime.preferred), described);
    var blocker = runtime.blocker && typeof runtime.blocker === 'object' ? runtime.blocker : {};
    var code = reachable ? '' : text(blocker.code);
    var headline = reachable
      ? 'Model runtime is reachable'
      : CODE_HEADLINES[code] || 'The model runtime is not reachable';
    // The raw transport detail deliberately never reaches the panel: it can
    // carry an operating-system errno. Operators get the backend remediation.
    var remediation = reachable ? '' : text(blocker.remediation);

    return {
      known: true,
      reachable: reachable,
      status: text(body.status) || (reachable ? 'ready' : 'degraded'),
      headline: headline,
      code: code,
      remediation: remediation,
      activePath: active.label,
      activePathState: active.state,
      candidates: described,
      externalAdaptersEnabled: runtime.external_adapters_enabled === true,
      nativeNote: NATIVE_NOTE,
      noKeyNote: NO_KEY_NOTE,
      message: [
        headline + '.',
        'Provider path: ' + active.label + ' — ' + active.state + '.',
        remediation ? 'What to do: ' + remediation : '',
        NATIVE_NOTE,
        NO_KEY_NOTE,
      ]
        .filter(Boolean)
        .join(' '),
    };
  }

  return {
    summarize: summarize,
    CODE_HEADLINES: CODE_HEADLINES,
    NATIVE_NOTE: NATIVE_NOTE,
    NO_KEY_NOTE: NO_KEY_NOTE,
  };
});
