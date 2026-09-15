/* Estate Scan report web app.
   Reads the embedded payload (a documented subset of findings.json), renders
   both Present and Explore modes from the one dataset, and needs no network.
   No composite score, no gauge anywhere -- the cover carries three facts and
   the register names the binding constraint.

   The embedded payload schema (subset of findings.json):
     meta      {run_id, generated_at, build, framing, site_name, profile,
                scan_started_at, scan_completed_at, grouping_mode,
                adoption_source, tool_version, query_set_version,
                app_template_version}
     facets    [{id, dimension, score, confidence, evidence, gates, finding}]
     domains   [{id, target_stage, readiness, gap, binding_constraints,
                 unscored_dimensions, confidence}]
     flags     [{id, severity, confidence, facet, domain, count}]
     coverage  [{measure, status, reason}]
     findings  {definition_multiplicity, security_exposure, retirement}
*/
(function () {
  "use strict";

  var DATA = JSON.parse(document.getElementById("findings-data").textContent);

  // Framing-light mode (report web app spec section 8): an account that rejects
  // a maturity ladder gets the same findings, coverage, and remediation with no
  // stage/score language. Driven from meta.framing so the one payload serves
  // both registers -- there is no second build and no second template.
  var FRAMING_LIGHT = ((DATA.meta || {}).framing === "light");

  var STAGES = {1: "Minimal", 2: "Emerging", 3: "Performing",
                4: "Optimizing", 5: "Leading", 6: "Autonomous"};

  // ---- tiny DOM helpers ----
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") n.className = attrs[k];
        else if (k === "text") n.textContent = attrs[k];
        else if (k === "html") n.innerHTML = attrs[k];
        else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
        else if (attrs[k] != null) n.setAttribute(k, attrs[k]);
      });
    }
    (kids || []).forEach(function (c) {
      if (c == null) return;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }
  function txt(s) { return document.createTextNode(s == null ? "" : String(s)); }
  function stageLabel(n) {
    if (n == null) return "unscored";
    return n + " · " + (STAGES[n] || "?");
  }
  function pct(x) { return Math.round((x || 0) * 100) + "%"; }
  function num(n) { return (n == null ? 0 : n).toLocaleString(); }

  var app = document.getElementById("app");
  var sections = [];

  function addSection(id, title, buildBody) {
    var sec = el("section", {class: "section", id: id, "data-title": title,
                             "aria-label": title});
    buildBody(sec);
    app.appendChild(sec);
    sections.push(sec);
  }

  // =====================================================================
  // Cover
  // =====================================================================
  function renderCover() {
    addSection("cover", "Cover", function (sec) {
      var m = DATA.meta || {};
      sec.classList.add("cover");
      sec.appendChild(el("p", {class: "section-kicker",
        text: FRAMING_LIGHT ? "Estate scan findings" : "Estate readiness"}));
      sec.appendChild(el("h1", {text: m.site_name || "Tableau estate"}));
      var window_ = (m.scan_started_at || "?") + " – " + (m.scan_completed_at || "?");
      sec.appendChild(el("p", {class: "cover-meta"}, [
        txt("Scanned " + window_ + "  ·  profile: " + (m.profile || "unclassified"))
      ]));

      var facts = el("div", {class: "facts"});
      if (FRAMING_LIGHT) {
        // No stages, no binding constraint: three counts drawn straight from
        // the findings, so the cover reads as observation, not a rating.
        var dm = (DATA.findings && DATA.findings.definition_multiplicity) || {};
        var sx = (DATA.findings && DATA.findings.security_exposure) || {};
        var rt = (DATA.findings && DATA.findings.retirement) || {};
        facts.appendChild(fact("Contested metric concepts",
          num(dm.contested_group_count), false));
        facts.appendChild(fact("Access rules in the view layer",
          num(sx.user_context_field_count), false));
        facts.appendChild(fact("Zero-view workbooks",
          num(rt.zero_view_workbooks), false));
      } else {
        // Three facts, drawn from the primary decision domain. No synthesis.
        var d = pickPrimaryDomain();
        facts.appendChild(fact("Current stage",
          d ? stageLabel(d.readiness) : "unscored", false));
        facts.appendChild(fact("Target stage",
          d ? stageLabel(d.target_stage) : "not declared", false));
        var binding = d && d.binding_constraints && d.binding_constraints.length
          ? d.binding_constraints.join(", ") : "none";
        facts.appendChild(fact("Binding constraint", binding, true));
      }
      sec.appendChild(facts);

      // What the scan measured and what it did not -- on the cover on purpose.
      var cov = DATA.coverage || [];
      var gaps = cov.filter(function (c) { return c.status !== "ok"; });
      var line = el("p", {class: "cover-scope"});
      line.appendChild(txt(cov.length
        ? (cov.length - gaps.length) + " of " + cov.length +
          " measures returned data. " +
          (gaps.length ? gaps.length + " could not be measured — an " +
            "unmeasured dimension is not a clean one. " : "")
        : "Coverage register empty. "));
      var link = el("a", {href: "#", text: "See coverage →"});
      link.addEventListener("click", function (e) { e.preventDefault(); openCoverage(); });
      line.appendChild(link);
      sec.appendChild(line);
    });
  }

  function fact(label, value, isBinding) {
    var f = el("div", {class: "fact" + (isBinding ? " binding" : "")});
    var lab = el("div", {class: "fact-label"}, [txt(label)]);
    if (isBinding) lab.appendChild(el("span", {class: "tag-binding", text: "BINDING"}));
    f.appendChild(lab);
    f.appendChild(el("div", {class: "fact-value", text: value}));
    return f;
  }

  function pickPrimaryDomain() {
    var ds = DATA.domains || [];
    if (!ds.length) return null;
    // The domain whose readiness is furthest below its declared target is the
    // one the conversation is about; ties fall to the first.
    var best = null, bestGap = -Infinity;
    ds.forEach(function (d) {
      var g = d.gap == null ? -Infinity : d.gap;
      if (g > bestGap) { bestGap = g; best = d; }
    });
    return best || ds[0];
  }

  // =====================================================================
  // Finding 1: definition multiplicity  (the persuading artifact)
  // =====================================================================
  function renderDefinitions() {
    var dm = (DATA.findings && DATA.findings.definition_multiplicity) || {};
    var groups = (dm.groups || []).slice();
    addSection("finding-definitions", "Finding 1 · Definition multiplicity",
      function (sec) {
        sec.classList.add("finding");
        sec.appendChild(el("p", {class: "section-kicker",
          text: "Finding 1 of 3 · speaks to the analytics owner"}));
        sec.appendChild(el("h2", {text: "Definition multiplicity"}));
        sec.appendChild(el("p", {class: "lede"}, [txt(
          groups.length + " metric concept(s) in scope; " +
          (dm.contested_group_count || 0) + " with no dominant variant.")]));

        var cols = [
          {key: "label", label: "Metric", num: false},
          {key: "variant_count", label: "Variants", num: true},
          {key: "workbooks_affected", label: "Workbooks", num: true},
          {key: "disagreeing_variants", label: "Disagreeing", num: true},
          {key: "variants_covering_80pct_views", label: "Cover 80%", num: true},
          {key: "dominant", label: "Dominant", num: false}
        ];
        // Default sort: absence of a dominant variant first (build brief 6),
        // then more disagreement, then more variants.
        var sortKey = "_default", sortDir = 1;
        var wrap = el("div", {class: "tbl-wrap"});
        var table = el("table", {class: "grid", id: "dm-table"});
        wrap.appendChild(table);
        sec.appendChild(wrap);
        sec.appendChild(copyButton(function () { return tableToTsv(table); }));

        function defaultCmp(a, b) {
          return (a.dominant - b.dominant) ||
            (b.disagreeing_variants - a.disagreeing_variants) ||
            (b.variant_count - a.variant_count) ||
            a.label.localeCompare(b.label);
        }
        function draw() {
          var rows = groups.slice();
          if (sortKey === "_default") rows.sort(defaultCmp);
          else rows.sort(function (a, b) {
            var av = a[sortKey], bv = b[sortKey];
            if (typeof av === "string") return sortDir * av.localeCompare(bv);
            return sortDir * ((av || 0) - (bv || 0));
          });
          table.innerHTML = "";
          var thead = el("thead"); var htr = el("tr");
          cols.forEach(function (c) {
            var th = el("th", {class: (c.num ? "num " : "") + "sortable",
              scope: "col", role: "button", tabindex: "0"}, [txt(c.label)]);
            if (sortKey === c.key)
              th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending");
            function doSort() {
              if (sortKey === c.key) sortDir = -sortDir;
              else { sortKey = c.key; sortDir = c.num ? -1 : 1; }
              draw();
            }
            th.addEventListener("click", doSort);
            th.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doSort(); }
            });
            htr.appendChild(th);
          });
          thead.appendChild(htr); table.appendChild(thead);
          var tb = el("tbody");
          rows.forEach(function (g) {
            var tr = el("tr", {class: "clickable", tabindex: "0",
              "aria-expanded": "false"});
            tr.appendChild(el("td", {}, [txt(g.label)]));
            tr.appendChild(el("td", {class: "num", text: num(g.variant_count)}));
            tr.appendChild(el("td", {class: "num", text: num(g.workbooks_affected)}));
            tr.appendChild(el("td", {class: "num", text: num(g.disagreeing_variants)}));
            tr.appendChild(el("td", {class: "num",
              text: num(g.variants_covering_80pct_views)}));
            var dcell = el("td", {}, [g.dominant
              ? txt("yes")
              : el("span", {class: "no-dominant", text: "no"})]);
            tr.appendChild(dcell);
            var detail = null;
            function toggle() {
              if (detail) { detail.remove(); detail = null;
                tr.setAttribute("aria-expanded", "false"); return; }
              detail = el("tr", {class: "detail-row"});
              var td = el("td", {colspan: String(cols.length)});
              td.appendChild(variantDetail(g));
              detail.appendChild(td);
              tr.parentNode.insertBefore(detail, tr.nextSibling);
              tr.setAttribute("aria-expanded", "true");
            }
            tr.addEventListener("click", toggle);
            tr.addEventListener("keydown", function (e) {
              if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
            });
            tb.appendChild(tr);
          });
          table.appendChild(tb);
        }
        draw();
        sec.appendChild(el("p", {class: "baseline-note", text:
          "Sorted by absence of a dominant variant, not raw variant count: a " +
          "contested concept is the harder adjudication."}));
      });
  }

  function variantDetail(g) {
    var box = el("div");
    // The same-period side-by-side (report web app spec section 4.2) -- present
    // only when the full-mode VDS step executed the variants. Renders the two
    // figures, their difference, and the material verdict; the raw values are
    // "[redacted]" in the presentation build and shown in the working build.
    if (g.execution) box.appendChild(groupExecution(g.execution));
    (g.variants || []).forEach(function (v) {
      var card = el("div", {class: "variant"});
      var head = el("div", {class: "variant-head"});
      var name = el("span", {class: "variant-name"}, [txt(v.field_name)]);
      if (v.usage_rank === 1) name.appendChild(txt(" "));
      head.appendChild(name);
      head.appendChild(el("span", {class: "rank-badge",
        text: "rank " + v.usage_rank + " · " + num(v.view_count) +
              " views · " + num(v.workbook_count) + " wb"}));
      card.appendChild(head);
      var bar = el("div", {class: "sharebar"});
      bar.appendChild(el("span", {style: "width:" + pct(v.view_share) + ";",
        "aria-label": pct(v.view_share) + " of group views"}));
      card.appendChild(bar);
      card.appendChild(el("div", {class: "baseline-note",
        text: pct(v.view_share) + " of group views · source: " +
              (v.datasource_name || "?") + " · owner: " +
              (v.owner == null ? "—" : v.owner) +
              " · resolution: " + (v.resolution_status || "?")}));
      // Presentation build redacts resolved_formula to "[redacted]"; working
      // build carries the readable logic. We render whatever is present and
      // never reconstruct it from anything else.
      if (v.resolved_formula != null) {
        if (v.resolved_formula === "[redacted]")
          card.appendChild(el("div", {class: "redacted",
            text: "Formula withheld in the presentation build."}));
        else
          card.appendChild(el("pre", {class: "formula", text: v.resolved_formula}));
      }
      if (v.execution) card.appendChild(variantExecutionNote(v.execution));
      box.appendChild(card);
    });
    return box;
  }

  // The group-level VDS rollup: reference field vs the most-material variant,
  // executed over the same agreed period. Raw values arrive already redacted in
  // the presentation build, so this never has to decide what to hide.
  function groupExecution(gx) {
    var box = el("div", {class: "execution"});
    box.appendChild(el("div", {class: "execution-head"}, [
      el("strong", {text: "Executed values"}),
      txt(gx.period ? " · period " + gx.period : ""),
      txt(gx.material_disagreement ? " · material disagreement"
                                   : " · within tolerance")]));
    var pair = gx.most_material_pair;
    if (pair) {
      var grid = el("div", {class: "execution-pair"});
      grid.appendChild(execCell(pair.reference_field, pair.reference_value,
        "reference"));
      grid.appendChild(execCell(pair.variant_field, pair.variant_value,
        "variant"));
      box.appendChild(grid);
      box.appendChild(el("div", {class: "baseline-note", text:
        "absolute difference " + execValue(pair.abs_diff) + " · relative " +
        (pair.rel_diff == null ? "—" : pct(pair.rel_diff)) +
        (pair.material ? " · material" : " · within tolerance")}));
    } else {
      box.appendChild(el("p", {class: "baseline-note",
        text: "No comparable pair was executed for this concept."}));
    }
    box.appendChild(el("p", {class: "baseline-note", text:
      num(gx.tested) + " variant(s) tested, " + num(gx.untested) +
      " not comparable."}));
    return box;
  }

  function execCell(field, value, kind) {
    return el("div", {class: "execution-cell " + kind}, [
      el("div", {class: "fact-label", text: field || "?"}),
      el("div", {class: "fact-value", text: execValue(value)})]);
  }

  // A number renders formatted; a redaction marker (or an absent value) renders
  // as-is. Never coerces "[redacted]" through the number formatter.
  function execValue(v) {
    if (typeof v === "number") return num(v);
    return v == null ? "—" : String(v);
  }

  function variantExecutionNote(ex) {
    var parts = ["executability: " + (ex.executability_class || "?")];
    if (ex.untested_reason) parts.push("reason: " + ex.untested_reason);
    if (ex.period) parts.push("period: " + ex.period);
    if (ex.value != null) parts.push("value: " + execValue(ex.value));
    if (ex.rel_diff != null)
      parts.push("Δ " + pct(ex.rel_diff) + (ex.material ? " (material)" : ""));
    return el("div", {class: "baseline-note", text: parts.join(" · ")});
  }

  // =====================================================================
  // Finding 2: security exposure  (blunt, short; for a security buyer)
  // =====================================================================
  function renderSecurity() {
    var s = (DATA.findings && DATA.findings.security_exposure) || {};
    addSection("finding-security", "Finding 2 · Security exposure",
      function (sec) {
        sec.classList.add("finding");
        sec.appendChild(el("p", {class: "section-kicker",
          text: "Finding 2 of 3 · speaks to the security / IT owner"}));
        sec.appendChild(el("h2", {text: "Security exposure"}));
        sec.appendChild(el("p", {class: "lede"}, [txt(
          num(s.user_context_field_count) + " calculated field(s) enforce access " +
          "in the visualization layer, across " + num(s.affected_workbook_count) +
          " workbook(s).")]));
        sec.appendChild(el("p", {text:
          "A programmatic query against the data source bypasses a rule enforced " +
          "only in a calculated field. Row-level entitlement belongs at the " +
          "source, not in the view."}));

        var det = el("details", {class: "expander"});
        det.appendChild(el("summary", {}, [
          txt("Affected workbooks (" + num((s.affected_workbooks || []).length) + ")"),
          severityChip(s.severity)]));
        var body = el("div", {class: "expander-body"});
        var wrap = el("div", {class: "tbl-wrap"});
        var t = el("table", {class: "grid"});
        var th = el("thead"); th.appendChild(el("tr", {}, [
          el("th", {scope: "col", text: "Workbook"}),
          el("th", {scope: "col", text: "Owner"})]));
        t.appendChild(th);
        var tb = el("tbody");
        (s.affected_workbooks || []).forEach(function (w) {
          tb.appendChild(el("tr", {}, [
            el("td", {}, [txt(w.name)]),
            el("td", {}, [txt(w.owner == null ? "—" : w.owner)])]));
        });
        t.appendChild(tb); wrap.appendChild(t); body.appendChild(wrap);
        det.appendChild(body);
        sec.appendChild(det);
      });
  }

  // =====================================================================
  // Finding 3: retirement case  (recoverable capacity; funds the rest)
  // =====================================================================
  function renderRetirement() {
    var r = (DATA.findings && DATA.findings.retirement) || {};
    addSection("finding-retirement", "Finding 3 · Retirement case",
      function (sec) {
        sec.classList.add("finding");
        sec.appendChild(el("p", {class: "section-kicker",
          text: "Finding 3 of 3 · speaks to the analytics budget owner"}));
        sec.appendChild(el("h2", {text: "Retirement case"}));
        var ul = el("ul");
        ul.appendChild(el("li", {text:
          num(r.zero_view_workbooks) + " of " + num(r.workbooks_total) +
          " workbooks drew no views in the window — recoverable capacity."}));
        ul.appendChild(el("li", {text:
          num(r.workbooks_covering_80pct_views) + " workbook(s) carry 80% of all " +
          num(r.total_views) + " views."}));
        ul.appendChild(el("li", {text:
          num(r.redundant_source_tables) + " upstream table(s) feed more than one " +
          "published source (max " + num(r.max_sources_per_table) +
          " on one table) — candidate consolidation."}));
        sec.appendChild(ul);
        sec.appendChild(el("p", {text:
          "Presented as recoverable capacity, not waste: retiring unused content " +
          "and consolidating redundant sources funds the remediation without new " +
          "money."}));
      });
  }

  // =====================================================================
  // Readiness by facet / dimension
  // =====================================================================
  function renderDimensions() {
    if (FRAMING_LIGHT) return;   // hook: stages hidden in framing-light mode
    var facets = DATA.facets || [];
    var binding = bindingFacetIds();
    addSection("dimensions", "Readiness by facet", function (sec) {
      sec.appendChild(el("h2", {text: "Readiness by facet"}));
      sec.appendChild(el("p", {text:
        "Evidence level is a visible attribute, not a footnote: a facet scored " +
        "from telemetry and one scored from an interview are not equally derived."}));
      if (!facets.length) {
        sec.appendChild(el("p", {text: "No facets scored."})); return;
      }
      facets.forEach(function (f) {
        var det = el("details", {class: "expander" +
          (binding[f.id] ? " row-binding" : "")});
        var sum = el("summary");
        var left = el("span", {}, [
          txt(f.id + "  "),
          binding[f.id] ? el("span", {class: "tag-binding", text: "BINDING"}) : null]);
        var right = el("span", {}, [
          evidenceChip(f),
          txt("  score " + (f.score == null ? "—" : f.score))]);
        sum.appendChild(left); sum.appendChild(right);
        det.appendChild(sum);
        var body = el("div", {class: "expander-body"});
        if (f.finding) body.appendChild(el("p", {text: f.finding}));
        body.appendChild(el("p", {class: "baseline-note", text:
          "dimension: " + (f.dimension || "?") + " · confidence: " +
          (f.confidence || "?") + " · gates: " +
          ((f.gates || []).join(", ") || "—")}));
        var fl = (DATA.flags || []).filter(function (x) { return x.facet === f.id; });
        if (fl.length) body.appendChild(flagList(fl));
        det.appendChild(body);
        sec.appendChild(det);
      });
    });
  }

  function bindingFacetIds() {
    var out = {};
    (DATA.domains || []).forEach(function (d) {
      (d.binding_constraints || []).forEach(function (id) { out[id] = true; });
    });
    return out;
  }

  // =====================================================================
  // Readiness register (per decision domain)
  // =====================================================================
  function renderRegister() {
    if (FRAMING_LIGHT) return;   // hook: register hidden in framing-light mode
    var domains = DATA.domains || [];
    addSection("register", "Readiness register", function (sec) {
      sec.appendChild(el("h2", {text: "Readiness register"}));
      if (!domains.length) {
        sec.appendChild(el("p", {text: "No decision domains scored."})); return;
      }
      domains.forEach(function (d) {
        var det = el("details", {class: "expander"});
        var sum = el("summary");
        sum.appendChild(el("span", {text: d.id}));
        sum.appendChild(el("span", {text:
          "target " + stageLabel(d.target_stage) + " · current " +
          stageLabel(d.readiness)}));
        det.appendChild(sum);
        var body = el("div", {class: "expander-body"});
        var binding = (d.binding_constraints || []).join(", ") || "none";
        body.appendChild(el("p", {}, [
          el("strong", {text: "Binding constraint: "}), txt(binding),
          el("span", {class: "tag-binding", text: "BINDING"})]));
        body.appendChild(el("p", {class: "baseline-note", text:
          "gap: " + (d.gap == null ? "—" : d.gap) + " · confidence: " +
          (d.confidence || "?")}));
        var unscored = d.unscored_dimensions || [];
        if (unscored.length)
          body.appendChild(el("p", {class: "baseline-note",
            text: "Unscored dimensions: " + unscored.join(", ")}));
        det.appendChild(body);
        sec.appendChild(det);
      });
    });
  }

  // =====================================================================
  // Remediation and cost to gate
  // =====================================================================
  function renderRemediation() {
    addSection("remediation", FRAMING_LIGHT ? "Where to start" : "Remediation",
      function (sec) {
        if (FRAMING_LIGHT) { renderRemediationLight(sec); return; }
        sec.appendChild(el("h2", {text: "Remediation and cost to gate"}));
        sec.appendChild(el("p", {text:
          "First moves are the binding constraints below. Effort, owner, and the " +
          "transition each is charged to are captured with the customer during the " +
          "engagement — the tool does not synthesize them."}));
        var ol = el("ol");
        (DATA.domains || []).forEach(function (d) {
          (d.binding_constraints || []).forEach(function (id) {
            ol.appendChild(el("li", {text:
              "Lift " + id + " to clear the " + d.id + " target (" +
              stageLabel(d.target_stage) + ")."}));
          });
        });
        var dm = (DATA.findings && DATA.findings.definition_multiplicity) || {};
        if (dm.contested_group_count)
          ol.appendChild(el("li", {text:
            "Adjudicate " + dm.contested_group_count +
            " contested metric concept(s) — charged once, not per transition."}));
        if (!ol.childNodes.length)
          ol.appendChild(el("li", {text: "No binding constraint scored."}));
        sec.appendChild(ol);
        sec.appendChild(el("p", {}, [
          el("strong", {text: "Attribution rule: "}),
          txt("definition adjudication is charged to a single transition, never " +
              "double-counted across two.")]));
        sec.appendChild(el("p", {}, [el("strong", {text: "Out of scope: "}),
          txt("material-disagreement query execution, permissions sampling, grain " +
              "and freshness flags, and any write to the Tableau site. Keeping this " +
              "list visible is what keeps the plan fundable.")]));
      });
  }

  // Framing-light remediation: the same first moves phrased straight from the
  // findings, with no stage, target, or transition language.
  function renderRemediationLight(sec) {
    sec.appendChild(el("h2", {text: "Where to start"}));
    sec.appendChild(el("p", {text:
      "The first moves come straight from the findings above. Effort and owner " +
      "are captured with the customer during the engagement — the tool does not " +
      "synthesize them."}));
    var ol = el("ol");
    var dm = (DATA.findings && DATA.findings.definition_multiplicity) || {};
    var sx = (DATA.findings && DATA.findings.security_exposure) || {};
    var rt = (DATA.findings && DATA.findings.retirement) || {};
    if (dm.contested_group_count)
      ol.appendChild(el("li", {text:
        "Adjudicate " + num(dm.contested_group_count) +
        " contested metric concept(s) to one agreed definition."}));
    if (sx.user_context_field_count)
      ol.appendChild(el("li", {text:
        "Move " + num(sx.user_context_field_count) + " access rule(s) out of the " +
        "visualization layer to the data source."}));
    if (rt.zero_view_workbooks)
      ol.appendChild(el("li", {text:
        "Retire " + num(rt.zero_view_workbooks) + " zero-view workbook(s) and " +
        "consolidate redundant sources to recover capacity."}));
    if (!ol.childNodes.length)
      ol.appendChild(el("li", {text: "No findings to act on."}));
    sec.appendChild(ol);
    sec.appendChild(el("p", {}, [el("strong", {text: "Out of scope: "}),
      txt("material-disagreement query execution, permissions sampling, grain " +
          "and freshness flags, and any write to the Tableau site.")]));
  }

  // =====================================================================
  // Baseline capture (editable, persisted to localStorage, exportable)
  // =====================================================================
  function renderBaseline() {
    var r = (DATA.findings && DATA.findings.retirement) || {};
    var dm = (DATA.findings && DATA.findings.definition_multiplicity) || {};
    var s = (DATA.findings && DATA.findings.security_exposure) || {};
    var seeds = [
      ["Contested metric concepts", dm.contested_group_count],
      ["Metric concepts in scope", (dm.groups || []).length],
      ["Zero-view workbooks", r.zero_view_workbooks],
      ["Workbooks carrying 80% of views", r.workbooks_covering_80pct_views],
      ["Redundant upstream source tables", r.redundant_source_tables],
      ["Access rules in the visualization layer", s.user_context_field_count]
    ];
    var key = "estate-scan-baseline:" + ((DATA.meta || {}).run_id || "run");
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { saved = {}; }

    addSection("baseline", "Baseline capture", function (sec) {
      sec.appendChild(el("h2", {text: "Baseline capture"}));
      sec.appendChild(el("p", {class: "baseline-note", text:
        "The cheapest, most perishable work in the program — capture it while " +
        "the room is together. Values persist to this browser only; browser " +
        "storage is not a system of record, so export before you rely on it."}));
      var hdr = el("div", {class: "baseline-row"});
      ["Measure", "Current value", "Source", "Date"].forEach(function (h) {
        hdr.appendChild(el("strong", {text: h}));
      });
      sec.appendChild(hdr);

      var rows = [];
      seeds.forEach(function (seed, i) {
        var rec = saved[i] || {};
        var row = el("div", {class: "baseline-row"});
        row.appendChild(el("label", {text: seed[0]}));
        var val = el("input", {type: "text", value:
          rec.value != null ? rec.value : (seed[1] == null ? "" : String(seed[1])),
          "aria-label": seed[0] + " value"});
        var src = el("input", {type: "text", value: rec.source || "",
          placeholder: "source", "aria-label": seed[0] + " source"});
        var dt = el("input", {type: "date", value: rec.date || "",
          "aria-label": seed[0] + " date"});
        row.appendChild(val); row.appendChild(src); row.appendChild(dt);
        sec.appendChild(row);
        rows.push({label: seed[0], val: val, src: src, dt: dt});
      });

      function collect() {
        var out = {};
        rows.forEach(function (r2, i) {
          out[i] = {label: r2.label, value: r2.val.value,
                    source: r2.src.value, date: r2.dt.value};
        });
        return out;
      }
      function persist() {
        try { localStorage.setItem(key, JSON.stringify(collect())); } catch (e) {}
      }
      rows.forEach(function (r2) {
        [r2.val, r2.src, r2.dt].forEach(function (inp) {
          inp.addEventListener("input", persist);
        });
      });

      var actions = el("div", {class: "baseline-actions"});
      actions.appendChild(el("button", {class: "ghost-btn", text: "Export JSON",
        onclick: function () {
          download("baseline.json", "application/json",
            JSON.stringify({run_id: (DATA.meta || {}).run_id,
                            captured: collect()}, null, 2));
        }}));
      actions.appendChild(el("button", {class: "ghost-btn", text: "Export CSV",
        onclick: function () {
          var lines = ["measure,current_value,source,date"];
          var c = collect();
          Object.keys(c).forEach(function (k) {
            var r3 = c[k];
            lines.push([r3.label, r3.value, r3.source, r3.date]
              .map(csvCell).join(","));
          });
          download("baseline.csv", "text/csv", lines.join("\n"));
        }}));
      sec.appendChild(actions);
    });
  }

  // =====================================================================
  // Coverage drawer (persistently reachable; the counterweight to a UI
  // that could hide an omission)
  // =====================================================================
  function renderCoverageDrawer() {
    var body = document.getElementById("coverage-body");
    var m = DATA.meta || {};
    var meta = el("ul", {class: "meta-list"});
    [["Run", m.run_id], ["Generated", m.generated_at], ["Build", m.build],
     ["Tool version", m.tool_version], ["Query set", m.query_set_version],
     ["App template", m.app_template_version],
     ["Grouping mode", m.grouping_mode], ["Adoption source", m.adoption_source],
     ["Scan started", m.scan_started_at], ["Scan completed", m.scan_completed_at]
    ].forEach(function (kv) {
      meta.appendChild(el("li", {}, [el("strong", {text: kv[0] + ": "}),
        txt(kv[1] == null ? "—" : kv[1])]));
    });
    body.appendChild(meta);

    body.appendChild(el("h3", {text: "Measures attempted"}));
    var cov = DATA.coverage || [];
    if (!cov.length) { body.appendChild(el("p", {text: "No coverage records."})); return; }
    var t = el("table", {class: "grid"});
    var th = el("thead"); th.appendChild(el("tr", {}, [
      el("th", {scope: "col", text: "Measure"}),
      el("th", {scope: "col", text: "Status"}),
      el("th", {scope: "col", text: "Reason"})]));
    t.appendChild(th);
    var tb = el("tbody");
    cov.forEach(function (c) {
      var ok = c.status === "ok";
      tb.appendChild(el("tr", {}, [
        el("td", {}, [txt(c.measure)]),
        el("td", {}, [el("span", {class: ok ? "status-ok" : "status-gap",
          text: c.status})]),
        el("td", {}, [txt(c.reason || "—")])]));
    });
    t.appendChild(tb); body.appendChild(t);
  }

  // ---- shared UI atoms ----
  function severityChip(sev) {
    if (!sev) return txt("");
    return el("span", {class: "sev " + sev, text: sev});
  }
  function evidenceChip(f) {
    // The scorer marks a facet "observed" (from telemetry) or "reported" (from
    // an interview). Anything reported/attested is the hollow chip.
    var kind = /interview|attest|report/i.test(f.evidence || f.confidence || "")
      ? "interview" : "telemetry";
    return el("span", {class: "evidence " + kind,
      text: f.evidence || (kind === "interview" ? "attested" : "measured")});
  }
  function flagList(flags) {
    var ul = el("ul");
    flags.forEach(function (fl) {
      ul.appendChild(el("li", {}, [txt(fl.id + " "), severityChip(fl.severity),
        txt(" count " + num(fl.count))]));
    });
    return ul;
  }
  function copyButton(getText) {
    return el("button", {class: "ghost-btn copy-btn", text: "Copy table",
      onclick: function (e) {
        var s = getText();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(s).then(flash(e.target), flash(e.target));
        } else { legacyCopy(s); flash(e.target)(); }
      }});
  }
  function flash(btn) {
    return function () {
      var old = btn.textContent; btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = old; }, 1200);
    };
  }
  function legacyCopy(s) {
    var ta = document.createElement("textarea");
    ta.value = s; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(ta);
  }
  function tableToTsv(table) {
    var out = [];
    table.querySelectorAll("tr").forEach(function (tr) {
      if (tr.classList.contains("detail-row")) return;
      var cells = [];
      tr.querySelectorAll("th,td").forEach(function (c) { cells.push(c.textContent.trim()); });
      out.push(cells.join("\t"));
    });
    return out.join("\n");
  }
  function csvCell(v) {
    v = v == null ? "" : String(v);
    return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }
  function download(name, mime, content) {
    var blob = new Blob([content], {type: mime});
    var a = el("a", {href: URL.createObjectURL(blob), download: name});
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  // =====================================================================
  // Mode handling + present-mode pager + keyboard nav
  // =====================================================================
  var mode = "present", current = 0;
  function setMode(next) {
    mode = next;
    document.body.classList.toggle("mode-present", next === "present");
    document.body.classList.toggle("mode-explore", next === "explore");
    document.getElementById("mode-present").classList.toggle("is-active", next === "present");
    document.getElementById("mode-explore").classList.toggle("is-active", next === "explore");
    document.getElementById("mode-present").setAttribute("aria-selected", next === "present");
    document.getElementById("mode-explore").setAttribute("aria-selected", next === "explore");
    document.getElementById("pager").setAttribute("aria-hidden", next !== "present");
    if (next === "present") showCurrent();
  }
  function showCurrent() {
    sections.forEach(function (s, i) { s.classList.toggle("is-current", i === current); });
    var label = document.getElementById("pager-label");
    var cur = sections[current];
    label.textContent = (current + 1) + " / " + sections.length + "  ·  " +
      (cur ? cur.getAttribute("data-title") : "");
    document.getElementById("pager-prev").disabled = current === 0;
    document.getElementById("pager-next").disabled = current === sections.length - 1;
    if (cur) cur.scrollIntoView({block: "start"});
  }
  function move(delta) {
    if (mode !== "present") return;
    current = Math.max(0, Math.min(sections.length - 1, current + delta));
    showCurrent();
  }

  // =====================================================================
  // Coverage drawer open/close
  // =====================================================================
  function openCoverage() {
    document.getElementById("coverage-panel").hidden = false;
    document.getElementById("drawer-scrim").hidden = false;
    document.getElementById("coverage-close").focus();
  }
  function closeCoverage() {
    document.getElementById("coverage-panel").hidden = true;
    document.getElementById("drawer-scrim").hidden = true;
    document.getElementById("coverage-open").focus();
  }

  // =====================================================================
  // Boot
  // =====================================================================
  function boot() {
    var banner = document.getElementById("build-banner");
    var build = (DATA.meta || {}).build || "working";
    banner.classList.add(build);
    banner.textContent = build === "working"
      ? "Working build — contains business logic"
      : "Presentation build";

    renderCover();
    renderDefinitions();
    renderSecurity();
    renderRetirement();
    renderDimensions();
    renderRegister();
    renderRemediation();
    renderBaseline();
    renderCoverageDrawer();

    document.getElementById("mode-present").addEventListener("click", function () { setMode("present"); });
    document.getElementById("mode-explore").addEventListener("click", function () { setMode("explore"); });
    document.getElementById("pager-prev").addEventListener("click", function () { move(-1); });
    document.getElementById("pager-next").addEventListener("click", function () { move(1); });
    document.getElementById("coverage-open").addEventListener("click", openCoverage);
    document.getElementById("coverage-close").addEventListener("click", closeCoverage);
    document.getElementById("drawer-scrim").addEventListener("click", closeCoverage);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closeCoverage(); return; }
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") { move(1); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { move(-1); }
    });

    setMode("present");
  }

  boot();
})();
