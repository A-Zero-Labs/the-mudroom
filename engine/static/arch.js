// Point at a step to see what it reads and writes. Point at a table to see what it holds,
// and which steps touch it. Click to pin the selection so you can scroll and read.
(function () {
  var scope = document.querySelector(".hero");
  var detail = document.querySelector(".detail");
  if (!scope || !detail) return;

  var tables = {}, steps = {}, locked = null;
  scope.querySelectorAll("[data-table]").forEach(function (el) { tables[el.dataset.table] = el; });
  detail.querySelectorAll(".step").forEach(function (p) { steps[p.dataset.for] = p; });

  function clear() {
    scope.querySelectorAll("[data-table], .stage").forEach(function (el) {
      el.classList.remove("read", "write", "on", "locked");
    });
    Object.keys(steps).forEach(function (k) { steps[k].classList.toggle("on", k === ""); });
  }

  function panel(key) {
    steps[""].classList.remove("on");
    if (steps[key]) steps[key].classList.add("on");
  }

  function showStage(stage) {
    stage.classList.add("on");
    panel(stage.dataset.stage);
    ["reads", "writes"].forEach(function (which) {
      (stage.dataset[which] || "").split(",").filter(Boolean).forEach(function (t) {
        if (tables[t]) tables[t].classList.add(which === "reads" ? "read" : "write");
      });
    });
  }

  // The inverse: a table shows which steps touch it, and how.
  function showTable(el) {
    el.classList.add("on");
    panel(el.dataset.stage);
    var name = el.dataset.table;
    scope.querySelectorAll(".stage").forEach(function (stage) {
      if ((stage.dataset.reads || "").split(",").indexOf(name) > -1) stage.classList.add("read");
      if ((stage.dataset.writes || "").split(",").indexOf(name) > -1) stage.classList.add("write");
    });
  }

  function show(el) {
    clear();
    if (el.dataset.table) { showTable(el); } else { showStage(el); }
  }

  function lock(el) {
    locked = el;
    show(el);
    el.classList.add("locked");
    detail.classList.add("locked");
  }

  function unlock() {
    locked = null;
    detail.classList.remove("locked");
    clear();
  }

  function target(e) {
    return e.target.closest ? e.target.closest(".stage, [data-table]") : null;
  }

  scope.addEventListener("mouseover", function (e) {
    if (locked) return;            // a pinned selection ignores the pointer
    var el = target(e);
    if (el) { show(el); } else if (e.target.closest(".arch, .dbcol")) { clear(); }
  });

  scope.addEventListener("mouseleave", function () { if (!locked) clear(); });

  scope.addEventListener("click", function (e) {
    var el = target(e);
    if (!el) { if (e.target.closest(".arch, .dbcol")) unlock(); return; }
    if (locked === el) { unlock(); return; }
    lock(el);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && locked) { unlock(); return; }
    if ((e.key === "Enter" || e.key === " ") && target(e)) {
      e.preventDefault();
      var el = target(e);
      if (locked === el) { unlock(); } else { lock(el); }
    }
  });

  scope.querySelectorAll(".stage, [data-table]").forEach(function (el) {
    el.addEventListener("focus", function () { if (!locked) show(el); });
    el.addEventListener("blur", function () { if (!locked) clear(); });
  });

  clear();
})();
