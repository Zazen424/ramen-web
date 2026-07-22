/*
 * Persistence layer. MVP uses localStorage so the app runs with zero backend
 * and no API keys. Swap this module for a real API client later -- the shape
 * of the state object is the contract the rest of the app depends on.
 *
 * State shape:
 *   {
 *     goal: string,
 *     current: { category, text, date } | null,  // today's open step
 *     history: [ { category, text, date, status } ],  // status: 'done' | 'skipped'
 *     streak: number,
 *     lastDoneDate: string | null   // YYYY-MM-DD
 *   }
 */
(function (global) {
  'use strict';

  var KEY = 'bdss.state.v1';

  function blank() {
    return {
      goal: '',
      current: null,
      history: [],
      streak: 0,
      lastDoneDate: null,
    };
  }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return blank();
      var parsed = JSON.parse(raw);
      // Merge onto blank so missing fields from older versions are filled.
      return Object.assign(blank(), parsed);
    } catch (e) {
      return blank();
    }
  }

  function save(state) {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {
      /* storage full or unavailable -- fail quietly in the MVP */
    }
  }

  function reset() {
    try {
      localStorage.removeItem(KEY);
    } catch (e) {
      /* ignore */
    }
  }

  global.BDSS_Store = { load: load, save: save, reset: reset, blank: blank };
})(window);
