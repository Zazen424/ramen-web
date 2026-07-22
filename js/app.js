/*
 * App controller. Wires the store + task generator to the DOM.
 * One step a day; yes or no. Completing at least one step a day grows the streak.
 */
(function () {
  'use strict';

  var Store = window.BDSS_Store;
  var Tasks = window.BDSS_Tasks;

  var state = Store.load();

  // --- date helpers (local time, YYYY-MM-DD) ---------------------------------
  function todayKey(d) {
    d = d || new Date();
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function daysBetween(aKey, bKey) {
    var a = new Date(aKey + 'T00:00:00');
    var b = new Date(bKey + 'T00:00:00');
    return Math.round((b - a) / 86400000);
  }

  function prettyDate(key) {
    try {
      return new Date(key + 'T00:00:00').toLocaleDateString(undefined, {
        weekday: 'short', month: 'short', day: 'numeric',
      });
    } catch (e) {
      return key;
    }
  }

  // --- element refs ----------------------------------------------------------
  var els = {
    onboarding: document.getElementById('view-onboarding'),
    daily: document.getElementById('view-daily'),
    dreamForm: document.getElementById('dream-form'),
    dreamInput: document.getElementById('dream-input'),
    goalText: document.getElementById('goal-text'),
    stepCategory: document.getElementById('step-category'),
    stepDate: document.getElementById('step-date'),
    stepText: document.getElementById('step-text'),
    stepActions: document.getElementById('step-actions'),
    stepDone: document.getElementById('step-done'),
    btnYes: document.getElementById('btn-yes'),
    btnNo: document.getElementById('btn-no'),
    btnGoFurther: document.getElementById('btn-go-further'),
    streakCount: document.getElementById('streak-count'),
    totalCount: document.getElementById('total-count'),
    historyList: document.getElementById('history-list'),
    historyEmpty: document.getElementById('history-empty'),
    editGoal: document.getElementById('edit-goal'),
    editDialog: document.getElementById('edit-dialog'),
    editForm: document.getElementById('edit-form'),
    editInput: document.getElementById('edit-input'),
  };

  // --- core actions ----------------------------------------------------------
  function ensureStep() {
    if (!state.current) {
      var step = Tasks.generateStep(state.goal, state.history);
      state.current = { category: step.category, text: step.text, date: todayKey() };
      Store.save(state);
    }
  }

  function completeCurrent() {
    if (!state.current) return;
    var today = todayKey();

    // Grow the streak only for the first completion of a new day.
    if (state.lastDoneDate !== today) {
      var gap = state.lastDoneDate ? daysBetween(state.lastDoneDate, today) : null;
      state.streak = gap === 1 ? state.streak + 1 : 1;
      state.lastDoneDate = today;
    }

    state.history.unshift({
      category: state.current.category,
      text: state.current.text,
      date: today,
      status: 'done',
    });
    state.current = null;
    Store.save(state);
  }

  function skipCurrent() {
    if (!state.current) return;
    state.history.unshift({
      category: state.current.category,
      text: state.current.text,
      date: todayKey(),
      status: 'skipped',
    });
    state.current = null;
    Store.save(state);
  }

  function totalDone() {
    return state.history.filter(function (h) { return h.status === 'done'; }).length;
  }

  // --- rendering -------------------------------------------------------------
  function show(view) {
    els.onboarding.hidden = view !== 'onboarding';
    els.daily.hidden = view !== 'daily';
  }

  function renderStepArea(justCompleted) {
    if (justCompleted) {
      els.stepActions.hidden = true;
      els.stepDone.hidden = false;
      return;
    }
    ensureStep();
    els.stepCategory.textContent = state.current.category;
    els.stepDate.textContent = prettyDate(state.current.date);
    els.stepText.textContent = state.current.text;
    els.stepActions.hidden = false;
    els.stepDone.hidden = true;
  }

  function renderHistory() {
    els.historyList.innerHTML = '';
    if (state.history.length === 0) {
      els.historyEmpty.hidden = false;
      return;
    }
    els.historyEmpty.hidden = true;
    state.history.forEach(function (h) {
      var li = document.createElement('li');
      li.className = 'history-item' + (h.status === 'skipped' ? ' history-skipped' : '');

      var icon = document.createElement('span');
      icon.className = 'history-icon';
      icon.textContent = h.status === 'done' ? '✅' : '⏭️';

      var body = document.createElement('div');
      body.className = 'history-body';

      var step = document.createElement('p');
      step.className = 'history-step';
      step.textContent = h.text;

      var when = document.createElement('p');
      when.className = 'history-when';
      when.textContent = (h.status === 'done' ? 'Done' : 'Skipped') + ' · ' + prettyDate(h.date) + ' · ' + h.category;

      body.appendChild(step);
      body.appendChild(when);
      li.appendChild(icon);
      li.appendChild(body);
      els.historyList.appendChild(li);
    });
  }

  function renderDaily(justCompleted) {
    els.goalText.textContent = state.goal;
    els.streakCount.textContent = state.streak;
    els.totalCount.textContent = totalDone();
    renderStepArea(justCompleted);
    renderHistory();
  }

  function route() {
    if (!state.goal) {
      show('onboarding');
    } else {
      show('daily');
      renderDaily(false);
    }
  }

  // --- events ----------------------------------------------------------------
  els.dreamForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var goal = els.dreamInput.value.trim();
    if (!goal) return;
    state.goal = goal;
    state.current = null;
    Store.save(state);
    show('daily');
    renderDaily(false);
  });

  Array.prototype.forEach.call(document.querySelectorAll('.chip'), function (chip) {
    chip.addEventListener('click', function () {
      els.dreamInput.value = chip.getAttribute('data-example');
      els.dreamInput.focus();
    });
  });

  els.btnYes.addEventListener('click', function () {
    completeCurrent();
    renderDaily(true);
  });

  els.btnNo.addEventListener('click', function () {
    skipCurrent();
    renderDaily(true);
  });

  els.btnGoFurther.addEventListener('click', function () {
    // Generate an additional step for the same day.
    var step = Tasks.generateStep(state.goal, state.history);
    state.current = { category: step.category, text: step.text, date: todayKey() };
    Store.save(state);
    renderDaily(false);
  });

  els.editGoal.addEventListener('click', function () {
    els.editInput.value = state.goal;
    if (typeof els.editDialog.showModal === 'function') {
      els.editDialog.showModal();
      // Scroll-lock fallback for browsers without :has() (restored on 'close').
      document.body.style.overflow = 'hidden';
    } else {
      // Fallback for browsers without <dialog>.
      var next = prompt('Edit or pivot your dream:', state.goal);
      if (next && next.trim()) {
        state.goal = next.trim();
        Store.save(state);
        renderDaily(false);
      }
    }
  });

  els.editForm.addEventListener('submit', function (e) {
    // The submitter's value tells us cancel vs save.
    var submitter = e.submitter || document.activeElement;
    if (submitter && submitter.value === 'cancel') return;
    var next = els.editInput.value.trim();
    if (next) {
      state.goal = next;
      Store.save(state);
      renderDaily(false);
    }
  });

  // Mobile has no Esc key: tapping the backdrop (the dialog's own hit area
  // outside the form) is the dismissal gesture users reach for first.
  els.editDialog.addEventListener('click', function (e) {
    if (e.target === els.editDialog) els.editDialog.close();
  });

  // Scroll-lock fallback for browsers without :has() support.
  els.editDialog.addEventListener('close', function () {
    document.body.style.overflow = '';
  });

  // --- mobile/PWA ------------------------------------------------------------
  // Ask the browser to protect localStorage from eviction (iOS ITP clears
  // script-writable storage after 7 days of no visits -- fatal for a streak).
  if (navigator.storage && navigator.storage.persist) {
    navigator.storage.persist().catch(function () { /* best effort */ });
  }

  // Offline support: the app shell is precached by the service worker.
  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { /* best effort */ });
    });
  }

  // --- go --------------------------------------------------------------------
  route();
})();
