/* =========================================================================
   FindMeGamer — page behaviour
   Classic script on purpose: the copy entry and mobile nav keep working when
   the page is opened straight from disk (file://), where ES modules are
   blocked. The WebGL scene is loaded separately, and is optional.
   ========================================================================= */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------ nav state */
  var nav = document.querySelector(".nav");
  var lastStuck = false;
  function onScroll() {
    if (!nav) return;
    var stuck = window.scrollY > 6;
    if (stuck !== lastStuck) {
      nav.classList.toggle("is-stuck", stuck);
      lastStuck = stuck;
    }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ------------------------------------------------------------ mobile nav */
  var toggle = document.querySelector("[data-nav-toggle]");
  var panel = document.getElementById("nav-panel");
  if (toggle && panel) {
    var setMenu = function (open) {
      toggle.setAttribute("aria-expanded", String(open));
      var chinese = document.documentElement.lang === "zh-CN";
      toggle.setAttribute("aria-label", open ? (chinese ? "关闭菜单" : "Close menu") : (chinese ? "打开菜单" : "Open menu"));
      panel.hidden = !open;
    };
    toggle.addEventListener("click", function () {
      setMenu(toggle.getAttribute("aria-expanded") !== "true");
    });
    panel.addEventListener("click", function (event) {
      if (event.target.closest("a, button")) setMenu(false);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setMenu(false);
        toggle.focus();
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth >= 900) setMenu(false);
    });
  }

  /* ---------------------------------------------------- reveal on scroll  */
  var revealables = document.querySelectorAll(".reveal");
  document.documentElement.classList.add("reveal-ready");
  if ("IntersectionObserver" in window && !reduceMotion) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -6% 0px", threshold: 0.06 }
    );
    revealables.forEach(function (el) {
      io.observe(el);
    });
  } else {
    revealables.forEach(function (el) {
      el.classList.add("is-in");
    });
  }

  /* -------------------------------------------------------------- copying */
  var promptEl = document.getElementById("setup-prompt");
  var consoleEl = document.querySelector("[data-console]");
  var statusEl = document.querySelector("[data-copy-status]");
  var statusTextEl = document.querySelector("[data-copy-status-text]");
  var heroSupport = document.querySelector(".hero__support");
  var defaultHeroSupport = heroSupport ? heroSupport.textContent.trim() : "";

  // Copy is bilingual: every string comes from data attributes on <body>, so the
  // two pages share one script and no English leaks into the Chinese build.
  var ui = document.body.dataset;
  var strings = {
    copy: ui.uiCopy || "Copy setup prompt",
    copied: ui.uiCopied || "Copied",
    copiedLong: ui.uiCopiedLong || "Copied. Paste it into your Agent.",
    copyError:
      ui.uiCopyError ||
      "Could not copy automatically. Select the prompt above and copy it manually.",
    selected:
      ui.uiSelected ||
      "Prompt selected. Press Command + C or Ctrl + C to copy.",
    copyErrorShort: ui.uiCopyErrorShort || "Copy failed",
    statusDefault: ui.uiStatusDefault || ""
  };

  function status(message, kind) {
    if (!statusEl || !statusTextEl) return;
    statusTextEl.textContent = message;
    statusEl.classList.remove("is-ok", "is-warn");
    if (kind === "ok") statusEl.classList.add("is-ok");
    if (kind === "warn") statusEl.classList.add("is-warn");
  }

  function setButtonState(button, done) {
    var label = button.querySelector("[data-copy-label]");
    var icon = button.querySelector("svg");
    button.classList.toggle("is-copied", done);
    if (label) label.textContent = done ? strings.copied : strings.copy;
    if (icon) {
      icon.innerHTML = done
        ? '<path d="m4 12 5 5L20 6" />'
        : '<rect x="8" y="8" width="12" height="13" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3" />';
    }
  }

  var buttonTimers = new Map();
  function flagButtons(done) {
    document.querySelectorAll("[data-copy-prompt]").forEach(function (button) {
      setButtonState(button, done);
      if (buttonTimers.has(button)) clearTimeout(buttonTimers.get(button));
      if (done) {
        buttonTimers.set(
          button,
          setTimeout(function () {
            setButtonState(button, false);
          }, 4200)
        );
      }
    });
  }

  function selectPrompt() {
    if (!promptEl) return false;
    try {
      var range = document.createRange();
      range.selectNodeContents(promptEl);
      var selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      promptEl.focus({ preventScroll: true });
      return true;
    } catch (error) {
      return false;
    }
  }

  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.setAttribute(
      "style",
      "position:fixed;top:0;left:-9999px;width:1px;height:1px;opacity:0"
    );
    document.body.appendChild(area);
    var ok = false;
    try {
      area.select();
      area.setSelectionRange(0, text.length);
      ok = document.execCommand("copy");
    } catch (error) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  function copyText(text) {
    return new Promise(function (resolve) {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
          function () {
            resolve(true);
          },
          function () {
            resolve(legacyCopy(text));
          }
        );
      } else {
        resolve(legacyCopy(text));
      }
    });
  }

  function handleCopy(button) {
    if (!promptEl) return;
    var text = promptEl.textContent;
    copyText(text).then(function (ok) {
      if (ok) {
        flagButtons(true);
        status(strings.copiedLong, "ok");
        if (consoleEl) consoleEl.classList.add("is-copied");
        if (heroSupport && button.closest(".hero")) {
          heroSupport.textContent = strings.copiedLong;
          setTimeout(function () {
            heroSupport.textContent = defaultHeroSupport;
          }, 4200);
        }
        setTimeout(function () {
          if (consoleEl) consoleEl.classList.remove("is-copied");
          status(strings.statusDefault);
        }, 5200);
      } else {
        var selected = selectPrompt();
        status(selected ? strings.selected : strings.copyError, "warn");
        // Only claim failure when we could not even select the text; otherwise
        // the prompt is selected and the visitor just needs to press copy.
        if (!selected) {
          var label = button.querySelector("[data-copy-label]");
          if (label) {
            label.textContent = strings.copyErrorShort;
            setTimeout(function () {
              label.textContent = strings.copy;
            }, 4200);
          }
        }
      }
    });
  }

  document.querySelectorAll("[data-copy-prompt]").forEach(function (button) {
    button.addEventListener("click", function () {
      handleCopy(button);
    });
  });

  document.querySelectorAll("[data-select-prompt]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (selectPrompt()) status(strings.selected);
    });
  });

  /* --------------------------------------------------------- live field */
  var fieldStage = document.querySelector("[data-field]");
  var connection = navigator.connection || {};
  var lite =
    connection.saveData === true ||
    (typeof navigator.hardwareConcurrency === "number" &&
      navigator.hardwareConcurrency <= 4);

  function webglAvailable() {
    try {
      var probe = document.createElement("canvas");
      var context = probe.getContext("webgl2") || probe.getContext("webgl");
      if (!context) return false;
      var lose = context.getExtension("WEBGL_lose_context");
      if (lose) lose.loseContext();
      return true;
    } catch (error) {
      return false;
    }
  }

  if (fieldStage && !reduceMotion && !lite && webglAvailable()) {
    var idle =
      window.requestIdleCallback ||
      function (callback) {
        return setTimeout(callback, 320);
      };
    idle(function () {
      import("./field.js")
        .then(function (module) {
          return module.init(fieldStage, { lite: lite });
        })
        .then(function (controller) {
          fieldStage.classList.add("is-live");
          if (controller && controller.dispose) {
            window.addEventListener("pagehide", controller.dispose);
          }
        })
        .catch(function () {
          /* The section is complete without it. */
        });
    });
  }

  /* ------------------------------------------------------------- hero scene */
  var sceneStage = document.querySelector("[data-scene]");
  if (sceneStage && !reduceMotion && !connection.saveData && webglAvailable()) {
    var idleScene =
      window.requestIdleCallback ||
      function (callback) {
        return setTimeout(callback, 120);
      };
    idleScene(function () {
      import("./scene.js")
        .then(function (module) {
          return module.init(sceneStage, { lite: lite });
        })
        .then(function (controller) {
          sceneStage.classList.add("is-live", "is-draggable");
          if (controller && controller.dispose) {
            window.addEventListener("pagehide", controller.dispose);
          }
        })
        .catch(function () {
          /* The illustration stays; nothing to report to the visitor. */
        });
    });
  }
  // A restored bfcache page must not expose disposed, blank WebGL canvases.
  window.addEventListener("pagehide", function () {
    document.querySelectorAll("[data-scene], [data-field]").forEach(function (stage) {
      stage.classList.remove("is-live", "is-draggable", "is-dragging");
    });
  });
})();
