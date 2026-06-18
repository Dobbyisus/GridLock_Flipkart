import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "file:///C:/Users/Shashwat%20Tiwari/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const WORKSPACE = "C:/Users/SHASHW~1/AppData/Local/Temp/codex-presentations/manual-20260618/gridlock-demo-deck";
const TMP_DIR = path.join(WORKSPACE, "tmp");
const PREVIEW_DIR = path.join(TMP_DIR, "preview");
const LAYOUT_DIR = path.join(TMP_DIR, "layout");
const QA_DIR = path.join(TMP_DIR, "qa");
const FINAL_PPTX = "C:/Users/Shashwat Tiwari/Desktop/GridLock_Round2/outputs/gridlock-project-demo.pptx";

const COLORS = {
  navy900: "#0a2a73",
  navy800: "#1e4faf",
  blue500: "#3a78ff",
  bg: "#f7f8fb",
  surface: "#ffffff",
  border: "#dde3ee",
  text: "#10224f",
  textSoft: "#64748b",
  low: "#22c1a7",
  medium: "#f3bf44",
  high: "#f18d38",
  critical: "#ee5353",
  station: "#111827",
  shadow: "#0f172a",
};

const slideSize = { width: 1280, height: 720 };
const page = { left: 72, top: 54, width: 1136, height: 612 };

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function addText(slide, {
  left, top, width, height, text, fontSize = 20, color = COLORS.text,
  bold = false, opacity = 100, align = "left", fontFace = "Aptos",
  name, italic = false,
}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name,
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontFace,
    fontSize,
    color: `${color}/${opacity}`,
    bold,
    italic,
    alignment: align,
  };
  return shape;
}

function addCard(slide, {
  left, top, width, height, fill = COLORS.surface, lineFill = COLORS.border,
  radius = "rounded-3xl", shadow = "shadow-md", name,
}) {
  return slide.shapes.add({
    geometry: "roundRect",
    name,
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: 1 },
    borderRadius: radius,
    shadow,
  });
}

function addPill(slide, { left, top, width, text, fill, color }) {
  const pill = slide.shapes.add({
    geometry: "roundRect",
    position: { left, top, width, height: 30 },
    fill,
    line: { style: "solid", fill, width: 0 },
    borderRadius: "rounded-full",
  });
  pill.text = text;
  pill.text.style = { fontFace: "Aptos", fontSize: 13, bold: true, color };
  return pill;
}

function addBulletList(slide, items, { left, top, width, lineGap = 32, fontSize = 20, color = COLORS.textSoft }) {
  items.forEach((item, index) => {
    addText(slide, {
      left,
      top: top + (index * lineGap),
      width,
      height: 28,
      text: `• ${item}`,
      fontSize,
      color,
      fontFace: "Aptos",
    });
  });
}

function addSectionTitle(slide, eyebrow, title, subtitle) {
  addText(slide, {
    left: page.left,
    top: page.top,
    width: 320,
    height: 22,
    text: eyebrow.toUpperCase(),
    fontSize: 13,
    color: COLORS.blue500,
    bold: true,
    fontFace: "Aptos",
  });
  addText(slide, {
    left: page.left,
    top: page.top + 30,
    width: 720,
    height: 60,
    text: title,
    fontSize: 32,
    color: COLORS.text,
    bold: true,
    fontFace: "Aptos Display",
  });
  if (subtitle) {
    addText(slide, {
      left: page.left,
      top: page.top + 80,
      width: 860,
      height: 42,
      text: subtitle,
      fontSize: 18,
      color: COLORS.textSoft,
      fontFace: "Aptos",
    });
  }
}

function addFooter(slide, text = "GridLock Project Demo") {
  addText(slide, {
    left: page.left,
    top: 684,
    width: 320,
    height: 18,
    text,
    fontSize: 11,
    color: COLORS.textSoft,
    fontFace: "Aptos",
  });
}

function buildCover(slide) {
  slide.background.fill = "linear(135deg, #071a4f 0%, #0a2a73 42%, #1e4faf 100%)";
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 860, top: 48, width: 320, height: 320 },
    fill: "radial(#ffffff/25 0%, #3a78ff/12 45%, #ffffff/0 100%)",
    line: { style: "solid", fill: "none", width: 0 },
  });
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 680, top: 350, width: 440, height: 260 },
    fill: "radial(#22c1a7/25 0%, #ffffff/0 75%)",
    line: { style: "solid", fill: "none", width: 0 },
  });
  addPill(slide, {
    left: 74,
    top: 76,
    width: 190,
    text: "CITY OPS INTELLIGENCE",
    fill: "#ffffff/18",
    color: "#ffffff",
  });
  addText(slide, {
    left: 74, top: 142, width: 700, height: 160,
    text: "GridLock",
    fontSize: 62,
    color: "#ffffff",
    bold: true,
    fontFace: "Aptos Display",
  });
  addText(slide, {
    left: 76, top: 242, width: 680, height: 110,
    text: "Adaptive traffic intelligence for city command centers",
    fontSize: 28,
    color: "#ffffff",
    fontFace: "Aptos",
  });
  addText(slide, {
    left: 76, top: 330, width: 620, height: 96,
    text: "One live command surface for hotspot monitoring, field deployment, route decisions, and weekly learning.",
    fontSize: 21,
    color: "#E7EEFF",
    fontFace: "Aptos",
  });

  const hero = addCard(slide, {
    left: 768, top: 108, width: 396, height: 486,
    fill: "#f8fbff", lineFill: "#c8d9ff", radius: "rounded-3xl", shadow: "shadow-xl",
  });
  addText(slide, {
    left: hero.position.left + 24, top: hero.position.top + 24, width: 160, height: 20,
    text: "LIVE DASHBOARD", fontSize: 12, color: COLORS.textSoft, bold: true, fontFace: "Aptos",
  });
  addText(slide, {
    left: hero.position.left + 24, top: hero.position.top + 54, width: 260, height: 28,
    text: "Command UI preview", fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display",
  });
  const leftRail = addCard(slide, {
    left: 792, top: 136, width: 122, height: 402,
    fill: "#ffffff", lineFill: "#dbe6f7", radius: "rounded-2xl", shadow: "shadow-sm",
  });
  const mapFrame = addCard(slide, {
    left: 928, top: 136, width: 210, height: 260,
    fill: "linear(180deg, #f7f8fb 0%, #ebf2ff 100%)", lineFill: "#dbe6f7", radius: "rounded-2xl", shadow: "shadow-sm",
  });
  const detail = addCard(slide, {
    left: 928, top: 408, width: 210, height: 130,
    fill: "#ffffff", lineFill: "#dbe6f7", radius: "rounded-2xl", shadow: "shadow-sm",
  });
  for (let i = 0; i < 3; i += 1) {
    addCard(slide, {
      left: 807, top: 170 + i * 106, width: 92, height: 82,
      fill: i === 0 ? COLORS.navy900 : "#f8fbff",
      lineFill: "#dbe6f7",
      radius: "rounded-2xl",
      shadow: "shadow-sm",
    });
  }
  [COLORS.low, COLORS.medium, COLORS.high, COLORS.critical].forEach((fill, idx) => {
    slide.shapes.add({
      geometry: "ellipse",
      position: { left: 972 + (idx % 2) * 80, top: 194 + Math.floor(idx / 2) * 74, width: 18, height: 18 },
      fill,
      line: { style: "solid", fill: "#ffffff", width: 2 },
      shadow: "shadow-sm",
    });
  });
  addText(slide, {
    left: detail.position.left + 18, top: detail.position.top + 18, width: 160, height: 20,
    text: "Priority Hotspot", fontSize: 12, color: COLORS.textSoft, bold: true, fontFace: "Aptos",
  });
  addText(slide, {
    left: detail.position.left + 18, top: detail.position.top + 42, width: 170, height: 48,
    text: "Impact 82 • Critical", fontSize: 20, color: COLORS.text, bold: true, fontFace: "Aptos Display",
  });
  addText(slide, {
    left: detail.position.left + 18, top: detail.position.top + 84, width: 160, height: 28,
    text: "22 officers • 30 barricades", fontSize: 14, color: COLORS.textSoft, fontFace: "Aptos",
  });
  addFooter(slide, "GridLock • Project Demo Deck");
}

function buildProblem(slide) {
  slide.background.fill = COLORS.bg;
  addSectionTitle(slide, "The Problem", "Traffic ops are still reactive", "Cities need one place to monitor incidents, coordinate response, and learn from every disruption.");
  const cards = [
    ["Fragmented tooling", "Event feeds, maps, and field decisions are split across disconnected systems."],
    ["Slow response loops", "Operators lose time deciding severity, deployment levels, and diversion strategy."],
    ["No learning memory", "What actually happened in the field rarely improves the next recommendation cycle."],
  ];
  cards.forEach(([title, body], idx) => {
    const card = addCard(slide, {
      left: page.left + idx * 384, top: 228, width: 352, height: 288,
      fill: idx === 1 ? "linear(180deg, #f9fbff 0%, #edf4ff 100%)" : COLORS.surface,
      lineFill: idx === 1 ? "#cfe0ff" : COLORS.border,
    });
    addText(slide, {
      left: card.position.left + 24, top: card.position.top + 30, width: 280, height: 34,
      text: title, fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display",
    });
    addText(slide, {
      left: card.position.left + 24, top: card.position.top + 84, width: 288, height: 120,
      text: body, fontSize: 19, color: COLORS.textSoft, fontFace: "Aptos",
    });
    slide.shapes.add({
      geometry: "ellipse",
      position: { left: card.position.left + 24, top: card.position.top + 220, width: 44, height: 44 },
      fill: idx === 0 ? "#eaf1ff" : idx === 1 ? "#e8f8f5" : "#fff2dd",
      line: { style: "solid", fill: "none", width: 0 },
    });
  });
  addFooter(slide);
}

function buildOverview(slide) {
  slide.background.fill = "linear(180deg, #ffffff 0%, #f7f8fb 100%)";
  addSectionTitle(slide, "Product Overview", "One operating surface", "GridLock combines live monitoring, response recommendations, route decisions, and a learning loop.");
  const center = addCard(slide, {
    left: 500, top: 256, width: 280, height: 170, fill: COLORS.navy900, lineFill: COLORS.navy900, shadow: "shadow-xl",
  });
  addText(slide, {
    left: 538, top: 300, width: 210, height: 42, text: "GridLock Core", fontSize: 30, color: "#ffffff", bold: true, fontFace: "Aptos Display", align: "center",
  });
  addText(slide, {
    left: 540, top: 346, width: 200, height: 54, text: "Command UI + Engine + Weekly Learning", fontSize: 17, color: "#e7eeff", fontFace: "Aptos", align: "center",
  });
  const nodes = [
    { left: 90, top: 176, title: "Monitor", body: "Hotspot feed, calendar windows, live severity." },
    { left: 908, top: 176, title: "Respond", body: "Officers, barricades, station alignment, diversions." },
    { left: 90, top: 438, title: "Route", body: "Alternative paths around impacted corridors." },
    { left: 908, top: 438, title: "Learn", body: "Weekly review, correction summary, retraining." },
  ];
  nodes.forEach((node) => {
    const card = addCard(slide, {
      left: node.left, top: node.top, width: 286, height: 136, fill: COLORS.surface, lineFill: "#d7e6ff", shadow: "shadow-md",
    });
    addText(slide, {
      left: card.position.left + 22, top: card.position.top + 22, width: 200, height: 28,
      text: node.title, fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display",
    });
    addText(slide, {
      left: card.position.left + 22, top: card.position.top + 62, width: 236, height: 58,
      text: node.body, fontSize: 17, color: COLORS.textSoft, fontFace: "Aptos",
    });
  });
  slide.shapes.connect(center, slide.shapes.items[1], { kind: "elbow", fromSide: "left", toSide: "right", line: { style: "solid", fill: "#9db9ff", width: 2 } });
  slide.shapes.connect(center, slide.shapes.items[2], { kind: "elbow", fromSide: "right", toSide: "left", line: { style: "solid", fill: "#9db9ff", width: 2 } });
  slide.shapes.connect(center, slide.shapes.items[3], { kind: "elbow", fromSide: "left", toSide: "right", line: { style: "solid", fill: "#9db9ff", width: 2 } });
  slide.shapes.connect(center, slide.shapes.items[4], { kind: "elbow", fromSide: "right", toSide: "left", line: { style: "solid", fill: "#9db9ff", width: 2 } });
  addFooter(slide);
}

function buildFrontend(slide) {
  slide.background.fill = COLORS.bg;
  addSectionTitle(slide, "Frontend Experience", "A synchronized command interface", "The feed, map, detail dock, route planner, and weekly review are designed to update together.");
  const dashboard = addCard(slide, {
    left: 86, top: 172, width: 1100, height: 454, fill: "#ffffff", lineFill: "#d7e0ef", shadow: "shadow-lg",
  });
  addCard(slide, { left: 110, top: 196, width: 280, height: 408, fill: "#f9fbff", lineFill: "#dbe6f7", shadow: "shadow-sm" });
  addCard(slide, { left: 410, top: 196, width: 540, height: 408, fill: "linear(180deg, #edf3ff 0%, #f8fbff 100%)", lineFill: "#dbe6f7", shadow: "shadow-sm" });
  addCard(slide, { left: 968, top: 246, width: 194, height: 190, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-sm" });
  addCard(slide, { left: 968, top: 452, width: 194, height: 152, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-sm" });
  for (let i = 0; i < 4; i += 1) {
    addCard(slide, { left: 128, top: 278 + i * 76, width: 244, height: 60, fill: i === 0 ? "#eef4ff" : "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-none" });
  }
  [COLORS.low, COLORS.medium, COLORS.high, COLORS.critical].forEach((fill, idx) => {
    slide.shapes.add({
      geometry: "ellipse",
      position: { left: 474 + (idx % 2) * 132, top: 276 + Math.floor(idx / 2) * 88, width: 20, height: 20 },
      fill, line: { style: "solid", fill: "#ffffff", width: 2 }, shadow: "shadow-sm",
    });
  });
  addText(slide, { left: 130, top: 214, width: 160, height: 22, text: "Operations Rail", fontSize: 22, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addText(slide, { left: 430, top: 214, width: 160, height: 22, text: "Interactive Map", fontSize: 22, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addText(slide, { left: 982, top: 264, width: 130, height: 22, text: "Detail Dock", fontSize: 22, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addText(slide, { left: 982, top: 470, width: 130, height: 22, text: "Route Planner", fontSize: 22, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  const labels = [
    { x: 126, y: 564, t: "Hotspot feed + week review entry" },
    { x: 440, y: 564, t: "Severity-coded map + police markers" },
    { x: 974, y: 564, t: "Field plan + route decisions" },
  ];
  labels.forEach((item) => addText(slide, { left: item.x, top: item.y, width: 270, height: 38, text: item.t, fontSize: 15, color: COLORS.textSoft, fontFace: "Aptos" }));
  addFooter(slide);
}

function buildBackend(slide) {
  slide.background.fill = "linear(180deg, #ffffff 0%, #f7f8fb 100%)";
  addSectionTitle(slide, "Backend + API Layer", "FastAPI as the command fabric", "The UI is served directly by FastAPI and backed by dedicated endpoints for scoring, routing, review, and weekly learning.");
  const left = addCard(slide, { left: 84, top: 194, width: 280, height: 380, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-md" });
  const mid = addCard(slide, { left: 430, top: 194, width: 366, height: 380, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-md" });
  const right = addCard(slide, { left: 862, top: 194, width: 320, height: 380, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-md" });
  addText(slide, { left: 108, top: 220, width: 180, height: 26, text: "Frontend Surface", fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addBulletList(slide, ["Dashboard shell", "Operations tab", "Weekly review tab", "Route planner", "Correction archive"], { left: 108, top: 270, width: 220, fontSize: 18, lineGap: 38 });
  addText(slide, { left: 454, top: 220, width: 220, height: 26, text: "FastAPI Endpoints", fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addBulletList(slide, ["/dashboard", "/dashboard/day/{date}", "/routes/recommend", "/feedback/log", "/learning/state + /learning/retrain"], { left: 454, top: 270, width: 286, fontSize: 18, lineGap: 38 });
  addText(slide, { left: 886, top: 220, width: 220, height: 26, text: "Engine + State", fontSize: 24, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
  addBulletList(slide, ["Impact scoring", "Resource recommendation", "Diversion logic", "Weekly retraining state", "Feedback log persistence"], { left: 886, top: 270, width: 240, fontSize: 18, lineGap: 38 });
  slide.shapes.connect(left, mid, { kind: "elbow", fromSide: "right", toSide: "left", line: { style: "solid", fill: COLORS.blue500, width: 3 }, head: { type: "arrow", width: "med", length: "med" } });
  slide.shapes.connect(mid, right, { kind: "elbow", fromSide: "right", toSide: "left", line: { style: "solid", fill: COLORS.blue500, width: 3 }, head: { type: "arrow", width: "med", length: "med" } });
  addFooter(slide);
}

function buildEngine(slide) {
  slide.background.fill = COLORS.bg;
  addSectionTitle(slide, "Intelligence Engine", "From raw event signals to operational decisions", "GridLock converts event attributes and spatial context into clear field recommendations.");
  const frame = addCard(slide, { left: 92, top: 194, width: 1090, height: 390, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-md" });
  const stepTitles = ["Inputs", "Scoring", "Recommendations", "Learning"];
  const stepBodies = [
    "Event cause, priority, road closure, location, time, attendance",
    "Impact score, risk level, hotspot context, corridor context",
    "Officers, barricades, diversions, route alternatives, alert level",
    "Feedback log, weekly correction, state update, archived summary",
  ];
  stepTitles.forEach((title, idx) => {
    const leftPos = 126 + idx * 258;
    addCard(slide, { left: leftPos, top: 250, width: 210, height: 212, fill: idx === 1 ? "linear(180deg, #eef4ff 0%, #f9fbff 100%)" : "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-sm" });
    addText(slide, { left: leftPos + 18, top: 272, width: 140, height: 24, text: title, fontSize: 23, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
    addText(slide, { left: leftPos + 18, top: 322, width: 164, height: 104, text: stepBodies[idx], fontSize: 17, color: COLORS.textSoft, fontFace: "Aptos" });
  });
  for (let i = 0; i < 3; i += 1) {
    slide.shapes.add({
      geometry: "rightArrow",
      position: { left: 347 + i * 258, top: 334, width: 46, height: 28 },
      fill: COLORS.blue500,
      line: { style: "solid", fill: COLORS.blue500, width: 0 },
    });
  }
  slide.charts.add("bar", {
    position: { left: 864, top: 486, width: 260, height: 74 },
    categories: ["Impact", "Route", "Learning"],
    series: [{ name: "Coverage", values: [5, 4, 4], fill: COLORS.navy800 }],
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 80 },
    hasLegend: false,
    xAxis: { textStyle: { fill: COLORS.textSoft, fontSize: 11 }, line: { style: "solid", fill: COLORS.border, width: 1 } },
    yAxis: { visible: false, majorGridlines: null },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fill: COLORS.text, fontSize: 11, bold: true } },
  });
  addFooter(slide);
}

function buildLoop(slide) {
  slide.background.fill = "linear(180deg, #ffffff 0%, #f7f8fb 100%)";
  addSectionTitle(slide, "Weekly Correction Loop", "The product gets sharper every week", "Operators log what actually happened in the field, then GridLock recalibrates the engine and preserves the weekly summary.");
  const centerX = 640;
  const centerY = 360;
  const ringNodes = [
    { x: centerX - 110, y: centerY - 180, title: "Review", body: "Operators log actual impact and severity." },
    { x: centerX + 120, y: centerY - 40, title: "Retrain", body: "Weekly correction updates learning state." },
    { x: centerX - 40, y: centerY + 142, title: "Archive", body: "Per-week summaries remain accessible." },
    { x: centerX - 280, y: centerY - 20, title: "Compare", body: "Predicted vs actual outcomes are measured." },
  ];
  const center = addCard(slide, { left: 520, top: 274, width: 238, height: 126, fill: COLORS.navy900, lineFill: COLORS.navy900, shadow: "shadow-xl" });
  addText(slide, { left: 556, top: 308, width: 170, height: 30, text: "Weekly Learning", fontSize: 28, color: "#ffffff", bold: true, fontFace: "Aptos Display", align: "center" });
  addText(slide, { left: 550, top: 342, width: 180, height: 40, text: "From feedback log to improved recommendations", fontSize: 15, color: "#e7eeff", fontFace: "Aptos", align: "center" });
  const cards = ringNodes.map((node) => {
    const card = addCard(slide, { left: node.x, top: node.y, width: 210, height: 104, fill: "#ffffff", lineFill: "#dbe6f7", shadow: "shadow-md" });
    addText(slide, { left: node.x + 18, top: node.y + 18, width: 120, height: 24, text: node.title, fontSize: 22, color: COLORS.text, bold: true, fontFace: "Aptos Display" });
    addText(slide, { left: node.x + 18, top: node.y + 50, width: 160, height: 38, text: node.body, fontSize: 14, color: COLORS.textSoft, fontFace: "Aptos" });
    return card;
  });
  cards.forEach((card) => {
    slide.shapes.connect(center, card, { kind: "elbow", line: { style: "solid", fill: "#9db9ff", width: 2 }, head: { type: "arrow", width: "sm", length: "sm" } });
  });
  addFooter(slide);
}

function buildDemoFlow(slide) {
  slide.background.fill = COLORS.bg;
  addSectionTitle(slide, "Live Demo Flow", "The 90-second story", "This is the fast-paced sequence that shows the product value without slowing the audience down.");
  const steps = [
    "Open dashboard and establish city command view",
    "Click a hotspot to sync feed, map, and detail dock",
    "Show route recommendation around impact zone",
    "Jump to calendar/week selector for operational context",
    "Open Weekly Review and show feedback capture",
    "Run Weekly Correction and reveal stored summary",
  ];
  steps.forEach((step, idx) => {
    const x = 104 + idx * 177;
    slide.shapes.add({
      geometry: "ellipse",
      position: { left: x + 50, top: 262, width: 48, height: 48 },
      fill: idx === 5 ? COLORS.low : COLORS.navy900,
      line: { style: "solid", fill: "#ffffff", width: 3 },
    });
    addText(slide, {
      left: x + 65, top: 274, width: 18, height: 18,
      text: String(idx + 1), fontSize: 18, color: "#ffffff", bold: true, fontFace: "Aptos", align: "center",
    });
    addText(slide, {
      left: x, top: 330, width: 150, height: 104,
      text: step, fontSize: 16, color: COLORS.text, bold: idx === 5, fontFace: "Aptos", align: "center",
    });
    if (idx < 5) {
      slide.shapes.add({
        geometry: "rightArrow",
        position: { left: x + 122, top: 278, width: 36, height: 16 },
        fill: "#9db9ff",
        line: { style: "solid", fill: "#9db9ff", width: 0 },
      });
    }
  });
  addCard(slide, { left: 314, top: 486, width: 652, height: 92, fill: "linear(180deg, #ffffff 0%, #edf4ff 100%)", lineFill: "#cfe0ff", shadow: "shadow-sm" });
  addText(slide, {
    left: 340, top: 512, width: 600, height: 36,
    text: "Goal: make every click trigger a visible update and end on the correction archive as the product memory moment.",
    fontSize: 18, color: COLORS.text, fontFace: "Aptos", align: "center",
  });
  addFooter(slide);
}

function buildWhy(slide) {
  slide.background.fill = "linear(145deg, #0a2a73 0%, #1e4faf 100%)";
  addText(slide, {
    left: page.left, top: 72, width: 240, height: 20, text: "WHY IT WINS", fontSize: 13, color: "#b8ccff", bold: true, fontFace: "Aptos",
  });
  addText(slide, {
    left: page.left, top: 110, width: 760, height: 60, text: "From reactive traffic management to adaptive city operations", fontSize: 42, color: "#ffffff", bold: true, fontFace: "Aptos Display",
  });
  const columns = [
    ["Operational clarity", "One surface for hotspots, maps, response plans, and route decisions."],
    ["Actionable backend intelligence", "Scores, diversions, station context, and route logic are exposed through clean APIs."],
    ["A system that learns", "Weekly correction closes the loop with real field feedback and preserved weekly memory."],
  ];
  columns.forEach(([title, body], idx) => {
    const card = addCard(slide, {
      left: 86 + idx * 374, top: 246, width: 330, height: 270,
      fill: "#ffffff/10", lineFill: "#ffffff/16", shadow: "shadow-lg",
    });
    addText(slide, {
      left: card.position.left + 24, top: card.position.top + 28, width: 250, height: 58, text: title, fontSize: 28, color: "#ffffff", bold: true, fontFace: "Aptos Display",
    });
    addText(slide, {
      left: card.position.left + 24, top: card.position.top + 116, width: 260, height: 108, text: body, fontSize: 18, color: "#dfe8ff", fontFace: "Aptos",
    });
  });
  addFooter(slide, "GridLock • Adaptive Command Infrastructure");
}

function buildClosing(slide) {
  slide.background.fill = "linear(180deg, #f7f8fb 0%, #ffffff 100%)";
  slide.shapes.add({
    geometry: "ellipse",
    position: { left: 934, top: 66, width: 230, height: 230 },
    fill: "radial(#3a78ff/20 0%, #ffffff/0 75%)",
    line: { style: "solid", fill: "none", width: 0 },
  });
  addPill(slide, {
    left: page.left, top: 110, width: 178, text: "PROJECT DEMO CLOSE", fill: "#eef4ff", color: COLORS.navy900,
  });
  addText(slide, {
    left: 72, top: 184, width: 820, height: 132, text: "GridLock turns city traffic operations into a live, learning command platform.", fontSize: 50, color: COLORS.text, bold: true, fontFace: "Aptos Display",
  });
  addText(slide, {
    left: 74, top: 344, width: 700, height: 78, text: "Monitor the city, prioritize the right hotspots, route around disruption, and get smarter after every week.", fontSize: 24, color: COLORS.textSoft, fontFace: "Aptos",
  });
  addCard(slide, { left: 74, top: 474, width: 420, height: 120, fill: "linear(180deg, #ffffff 0%, #eff4ff 100%)", lineFill: "#cfe0ff", shadow: "shadow-md" });
  addText(slide, {
    left: 100, top: 506, width: 360, height: 54, text: "Frontend + Backend + Engine + Learning Loop\nall presented as one demoable product story.", fontSize: 20, color: COLORS.text, bold: true, fontFace: "Aptos",
  });
  addFooter(slide, "GridLock • End of Demo Deck");
}

async function main() {
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
  await fs.mkdir(LAYOUT_DIR, { recursive: true });
  await fs.mkdir(QA_DIR, { recursive: true });

  const presentation = Presentation.create({ slideSize });

  buildCover(presentation.slides.add());
  buildProblem(presentation.slides.add());
  buildOverview(presentation.slides.add());
  buildFrontend(presentation.slides.add());
  buildBackend(presentation.slides.add());
  buildEngine(presentation.slides.add());
  buildLoop(presentation.slides.add());
  buildDemoFlow(presentation.slides.add());
  buildWhy(presentation.slides.add());
  buildClosing(presentation.slides.add());

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    const png = await presentation.export({ slide, format: "png", scale: 1 });
    await writeBlob(path.join(PREVIEW_DIR, `${stem}.png`), png);
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(LAYOUT_DIR, `${stem}.layout.json`), await layout.text(), "utf8");
  }

  const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
  await writeBlob(path.join(PREVIEW_DIR, "deck-montage.webp"), montage);

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(FINAL_PPTX);

  const qa = [
    "QA summary",
    "- Slide count: 10",
    "- Theme: derived from GridLock frontend palette",
    "- Content: frontend, backend, engine, learning loop, and demo flow covered",
    "- Output: editable PPTX exported with native shapes/text/charts",
  ].join("\n");
  await fs.writeFile(path.join(QA_DIR, "visual-qa.txt"), qa, "utf8");

  const stat = await fs.stat(FINAL_PPTX);
  console.log(JSON.stringify({ finalPptx: FINAL_PPTX, bytes: stat.size, slideCount: 10 }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
