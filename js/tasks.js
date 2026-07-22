/*
 * Task generator.
 *
 * MVP: a local, offline heuristic that turns a big goal into a credible next
 * small step. It rotates through categories so the path stays varied and
 * always favors learning, research, skills, and relationships -- never
 * "buy this asset" financial advice.
 *
 * The real product will replace `generateStep` with a call to the Claude API
 * (claude-opus-4-8) that takes the goal plus the user's history and returns
 * the next step. The function signature below is the seam: keep it returning
 * `{ category, text }` and the rest of the app does not change.
 *
 *   async function generateStepWithAI(goal, history) {
 *     const res = await fetch('/api/next-step', {
 *       method: 'POST',
 *       headers: { 'Content-Type': 'application/json' },
 *       body: JSON.stringify({ goal, history }),
 *     });
 *     return res.json(); // { category, text }
 *   }
 */
(function (global) {
  'use strict';

  // Categories are deliberately learning- and action-oriented.
  var CATEGORIES = [
    {
      key: 'Learn',
      templates: [
        'Spend 20 minutes reading the basics of what it takes to {goalShort}. Write down one thing that surprised you.',
        'Watch one short video or read one article that explains a fundamental behind "{goal}".',
        'Define one term or concept you keep running into related to "{goal}" until you could explain it to a friend.',
      ],
    },
    {
      key: 'Research',
      templates: [
        'List three people or organizations who have already done something like "{goal}". Note how they started.',
        'Find one real number that matters for "{goal}" (a cost, a timeline, a market size) and write it down.',
        'Spend 15 minutes mapping the supply chain, regulations, or systems involved in "{goal}".',
      ],
    },
    {
      key: 'Connect',
      templates: [
        'Reach out to one person who knows more than you about "{goal}". A short message counts.',
        'Find one community, forum, or group focused on this area and join it.',
        'Write down a single question you would ask an expert about "{goal}", then find where to ask it.',
      ],
    },
    {
      key: 'Build',
      templates: [
        'Take the smallest possible concrete action toward "{goal}" today -- something you can finish in 30 minutes.',
        'Draft a one-paragraph version of your plan for "{goal}". Rough is fine.',
        'Identify the very next physical or digital step and do just that one step.',
      ],
    },
    {
      key: 'Reflect',
      templates: [
        'Write two sentences: what do you understand about "{goal}" now that you did not a week ago?',
        'Decide whether your goal still fits. Keep it, sharpen it, or pivot -- then write why.',
        'Name the one thing most likely to stop you, and one small way to lower that risk.',
      ],
    },
  ];

  function shorten(goal) {
    var g = String(goal || '').trim();
    // Strip a leading verb-ish "I want to / want to / to" so templates read well.
    g = g.replace(/^(i\s+(really\s+)?want\s+to\s+|want\s+to\s+|to\s+)/i, '');
    return g.charAt(0).toLowerCase() + g.slice(1);
  }

  // Simple deterministic-ish pick so the same day index gives a stable step,
  // but variety across days. `seed` is the count of steps already taken.
  function pick(arr, seed) {
    return arr[Math.abs(seed) % arr.length];
  }

  /**
   * Generate the next step.
   * @param {string} goal - the user's big dream.
   * @param {Array}  history - prior entries (used here only for rotation count).
   * @returns {{category: string, text: string}}
   */
  function generateStep(goal, history) {
    var count = Array.isArray(history) ? history.length : 0;
    var cat = pick(CATEGORIES, count);
    var template = pick(cat.templates, Math.floor(count / CATEGORIES.length));
    var text = template
      .replace(/\{goalShort\}/g, shorten(goal))
      .replace(/\{goal\}/g, String(goal || '').trim());
    return { category: cat.key, text: text };
  }

  global.BDSS_Tasks = { generateStep: generateStep };
})(window);
