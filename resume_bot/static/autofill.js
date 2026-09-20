/* One-click form autofill for job application portals.
   Matches fields by label text, name, id, placeholder and aria-label rather
   than per-site selectors, so it works anywhere. Multi-step forms render the
   next page into the same document, so a MutationObserver refills as new
   fields appear. Fills only empty fields. Never submits anything. */
(function () {
  var P = window.__RB_PROFILE__;
  if (!P) { alert("Profile not loaded."); return; }

  var RULES = [
    [/first\s*name|given\s*name|fname/i,                      P.first_name],
    [/last\s*name|family\s*name|surname|lname/i,              P.last_name],
    [/full\s*name|^\s*name\s*$|your\s*name|candidate\s*name/i, P.full_name],
    [/e[-\s]?mail/i,                                          P.email],
    [/phone|mobile|contact\s*number|telephone|cell/i,         P.phone],
    [/linked\s*in/i,                                          P.linkedin],
    [/git\s*hub/i,                                            P.github],
    [/portfolio|personal\s*(site|website)|website|blog/i,     P.portfolio],
    [/notice\s*period/i,                                      P.notice],
    [/current\s*(company|employer|organi[sz]ation)/i,         P.current_company],
    [/current\s*(ctc|salary|compensation)/i,                  P.current_ctc],
    [/expected\s*(ctc|salary|compensation)/i,                 P.expected_ctc],
    [/(total\s*)?(years?\s*of\s*)?experience|yoe/i,           P.experience],
    [/(current\s*)?(designation|job\s*title|role|position)/i, P.title],
    [/college|university|institution|school/i,                P.education],
    [/degree|qualification/i,                                 P.degree],
    [/current\s*(city|location)|city|location|based/i,        P.location]
  ];

  /* Two signals, deliberately separate. "own" is what belongs to THIS field:
     its attributes and its own label. "ctx" is surrounding text, which is
     shared with sibling fields - matching on it first made LinkedIn inherit
     the phone rule because both labels sat in one container. */
  function signals(el) {
    var own = [el.name, el.id, el.placeholder,
               el.getAttribute("aria-label") || "",
               el.getAttribute("data-testid") || ""];
    if (el.id) {
      try {
        var l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l) own.push(l.textContent);
      } catch (e) {}
    }
    var lab = el.closest("label");
    if (lab) {
      /* only this label's own text, not nested sibling fields */
      var clone = lab.cloneNode(true);
      clone.querySelectorAll("input,select,textarea,label").forEach(function (n) {
        n.remove();
      });
      own.push(clone.textContent);
    }
    var ctx = "";
    var w = el.closest("div,fieldset,li,td,section");
    for (var i = 0; w && i < 3; i++, w = w.parentElement) {
      var t = (w.textContent || "").trim();
      if (t && t.length < 160) { ctx = t; break; }
    }
    return { own: own.join(" ").slice(0, 300), ctx: ctx.slice(0, 300) };
  }

  function setValue(el, v) {
    var proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, v);
    el.dispatchEvent(new Event("input",  { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  var total = 0;

  function fillNow() {
    var filled = 0;
    var els = document.querySelectorAll(
      'input[type="text"],input[type="email"],input[type="tel"],input[type="url"],' +
      'input:not([type]),input[type="search"],textarea');
    for (var j = 0; j < els.length; j++) {
      var el = els[j];
      if (el.disabled || el.readOnly || el.offsetParent === null) continue;
      if (el.dataset.rbDone) continue;
      if ((el.value || "").trim()) { el.dataset.rbDone = "1"; continue; }
      var sig = signals(el);
      var hit = -1;
      for (var i = 0; i < RULES.length; i++) {
        if (RULES[i][1] && RULES[i][0].test(sig.own)) { hit = i; break; }
      }
      if (hit < 0) {                    /* fall back to surrounding text */
        for (var i = 0; i < RULES.length; i++) {
          if (RULES[i][1] && RULES[i][0].test(sig.ctx)) { hit = i; break; }
        }
      }
      {
        var i = hit;
        if (i >= 0) {
          setValue(el, RULES[i][1]);
          el.dataset.rbDone = "1";
          el.style.outline = "2px solid #0ca30c";
          (function (n) { setTimeout(function () { n.style.outline = ""; }, 1600); })(el);
          filled++;
        }
      }
    }
    total += filled;
    return filled;
  }

  if (window.__RB_WIDGET__) { window.__RB_SAY__(fillNow()); return; }

  var bar = document.createElement("div");
  bar.style.cssText = "position:fixed;z-index:2147483647;bottom:20px;right:20px;" +
    "background:#12121a;color:#fff;padding:9px 13px;border-radius:12px;display:flex;" +
    "gap:10px;align-items:center;font:13px/1.3 system-ui,sans-serif;" +
    "box-shadow:0 6px 28px rgba(0,0,0,.35)";
  var label = document.createElement("span");
  var btn = document.createElement("button");
  btn.textContent = "Fill";
  btn.style.cssText = "background:#2a78d6;color:#fff;border:0;border-radius:7px;" +
    "padding:5px 12px;font:600 13px system-ui,sans-serif;cursor:pointer";
  var auto = document.createElement("label");
  auto.style.cssText = "display:flex;gap:5px;align-items:center;cursor:pointer;opacity:.85";
  var cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = true; cb.style.cssText = "margin:0;cursor:pointer";
  auto.appendChild(cb); auto.appendChild(document.createTextNode("auto"));
  var close = document.createElement("span");
  close.textContent = "×";
  close.style.cssText = "cursor:pointer;opacity:.6;font-size:17px;line-height:1;padding:0 3px";
  bar.appendChild(label); bar.appendChild(btn); bar.appendChild(auto); bar.appendChild(close);
  document.body.appendChild(bar);

  window.__RB_WIDGET__ = bar;
  window.__RB_SAY__ = function (n) {
    label.textContent = n ? "filled " + n : "nothing new";
    setTimeout(function () { label.textContent = total + " filled"; }, 1800);
  };

  btn.onclick = function () { window.__RB_SAY__(fillNow()); };
  close.onclick = function () { obs.disconnect(); bar.remove(); window.__RB_WIDGET__ = null; };

  var pending = null;
  var obs = new MutationObserver(function () {
    if (!cb.checked || pending) return;
    pending = setTimeout(function () {
      pending = null;
      var n = fillNow();
      if (n) window.__RB_SAY__(n);
    }, 400);
  });
  obs.observe(document.body, { childList: true, subtree: true });

  window.__RB_SAY__(fillNow());
})();
