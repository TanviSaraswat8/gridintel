// Theme + shared components (dark industrial operator UI).
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

export const C = {
  bg: "#090c11", bg2: "#0c1117", panel: "#121922", panel2: "#18212c", line: "#1d2834", line2: "#2a3a4c",
  text: "#e4eaf1", dim: "#93a1b2", faint: "#5f6c7d", accent: "#38c8e8",
  NORMAL: "#3cc483", WATCH: "#e9c04a", WARNING: "#f09a3e", "HIGH RISK": "#f0544f", CRITICAL: "#ff2d6f", cyan: "#38c8e8",
};
export const MONO = "monospace";

export const riskColor = (cat) => C[cat] || C.faint;
export const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? "—" : String(+Number(v).toFixed(d)));
// Log sheets record the day's last reading as 24:00; stored as next-day 00:00, shown as 24:00 of the log day.
const shift24 = (t) => {
  if (!t || t.slice(11, 16) !== "00:00") return [t, t ? t.slice(11, 16) : ""];
  const d = new Date(t.slice(0, 10) + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() - 1);
  return [d.toISOString().slice(0, 10), "24:00"];
};
export const tsFmt = (t0) => {
  if (!t0) return "—";
  const [t, hh] = shift24(t0);
  const m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${t.slice(8, 10)} ${m[+t.slice(5, 7) - 1]} ${t.slice(0, 4)}  ${hh}`;
};
export const hourFmt = (t) => (t ? shift24(t)[1] : "");

export function Badge({ cat, small }) {
  const c = riskColor(cat);
  return (
    <View style={[s.badge, { borderColor: c, backgroundColor: c + "22" }, small && { paddingVertical: 1, paddingHorizontal: 5 }]}>
      <Text style={[s.badgeT, { color: cat === "HIGH RISK" ? "#ff8c8c" : c }, small && { fontSize: 9 }]}>{cat || "N/A"}</Text>
    </View>
  );
}

export function Panel({ title, hint, children, style }) {
  return (
    <View style={[s.panel, style]}>
      {title ? (
        <View style={s.panelHead}>
          <Text style={s.panelTitle}>{title}</Text>
          {hint ? <Text style={s.hint}>{hint}</Text> : null}
        </View>
      ) : null}
      {children}
    </View>
  );
}

export function Tile({ label, value, unit, name, flag }) {
  return (
    <View style={[s.tile, flag && { borderTopColor: C.WARNING }]}>
      <Text style={s.tileK} numberOfLines={1}>{label}</Text>
      <Text style={s.tileV} numberOfLines={1}>
        {value}<Text style={s.tileU}> {unit}</Text>
      </Text>
      {name ? <Text style={s.tileN} numberOfLines={1}>{name}</Text> : null}
    </View>
  );
}

export function Btn({ title, onPress, kind, style, disabled }) {
  const k = kind === "go" ? { borderColor: "#2f6f4a", backgroundColor: "#13281d" } : kind === "primary" ? { borderColor: C.accent, backgroundColor: "#13283a" } : {};
  return (
    <Pressable onPress={onPress} disabled={disabled} style={({ pressed }) => [s.btn, k, pressed && { opacity: 0.7 }, disabled && { opacity: 0.4 }, style]}>
      <Text style={[s.btnT, kind === "go" && { color: "#9fe0b8" }]}>{title}</Text>
    </Pressable>
  );
}

export function ModeBanner({ status }) {
  return (
    <View style={s.mode}>
      <View style={s.modeBadge}><Text style={s.modeBadgeT}>HISTORICAL REPLAY</Text></View>
      <Text style={s.modeT}>{status ? `${tsFmt(status.timestamp)} · ${status.mode}` : "connecting…"}</Text>
    </View>
  );
}

export function Loading({ text }) {
  return (
    <View style={{ padding: 40, alignItems: "center" }}>
      <ActivityIndicator color={C.accent} />
      <Text style={{ color: C.dim, marginTop: 10 }}>{text || "Loading…"}</Text>
    </View>
  );
}

export function ErrorBox({ error, onRetry }) {
  return (
    <Panel title="Connection problem">
      <Text style={{ color: C.dim, marginBottom: 10 }}>{String(error)}</Text>
      {onRetry ? <Btn title="RETRY" onPress={onRetry} /> : null}
    </Panel>
  );
}

// Minimal column chart (no external chart library needed in Expo Go).
export function Columns({ values, labels, height = 90, color = C.accent, colorFn, baseline, unit }) {
  const vals = values.map((v) => (v === null || v === undefined ? null : +v));
  const nums = vals.filter((v) => v !== null);
  if (!nums.length) return <Text style={{ color: C.faint }}>No data</Text>;
  let lo = Math.min(...nums, baseline ?? Infinity), hi = Math.max(...nums, baseline ?? -Infinity);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.1; lo = Math.max(lo - pad, Math.min(...nums) >= 0 ? 0 : lo - pad); hi += pad;
  const y = (v) => ((v - lo) / (hi - lo)) * height;
  return (
    <View>
      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
        <Text style={s.axis}>{fmt(hi, 1)} {unit || ""}</Text>
      </View>
      <View style={{ height, flexDirection: "row", alignItems: "flex-end", borderBottomWidth: 1, borderColor: C.line2 }}>
        {baseline !== undefined && baseline !== null ? (
          <View style={{ position: "absolute", left: 0, right: 0, bottom: y(baseline), borderTopWidth: 1, borderStyle: "dashed", borderColor: C.dim }} />
        ) : null}
        {vals.map((v, i) => (
          <View key={i} style={{ flex: 1, marginHorizontal: 1, height: v === null ? 0 : Math.max(2, y(v)), backgroundColor: colorFn ? colorFn(v, i) : color, opacity: i === vals.length - 1 ? 1 : 0.75 }} />
        ))}
      </View>
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginTop: 3 }}>
        <Text style={s.axis}>{labels?.[0] || ""}</Text>
        <Text style={s.axis}>{fmt(lo, 1)}</Text>
        <Text style={s.axis}>{labels?.[labels.length - 1] || ""}</Text>
      </View>
    </View>
  );
}

export const riskFill = (v) => (v > 90 ? C.CRITICAL : v > 75 ? C["HIGH RISK"] : v > 55 ? C.WARNING : v > 30 ? C.WATCH : C.NORMAL);

export const s = StyleSheet.create({
  badge: { borderWidth: 1, borderRadius: 2, paddingVertical: 3, paddingHorizontal: 7, alignSelf: "flex-start" },
  badgeT: { fontFamily: MONO, fontWeight: "700", fontSize: 10, letterSpacing: 1 },
  panel: { backgroundColor: C.panel, borderWidth: 1, borderColor: C.line, borderRadius: 3, padding: 12, marginBottom: 10 },
  panelHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  panelTitle: { color: C.dim, fontFamily: MONO, fontWeight: "700", fontSize: 11, letterSpacing: 1.5 },
  hint: { color: C.faint, fontSize: 10, flexShrink: 1, textAlign: "right", marginLeft: 8 },
  tile: { width: "48.5%", backgroundColor: C.panel, borderWidth: 1, borderColor: C.line, borderTopWidth: 2, borderTopColor: C.line2, padding: 10, marginBottom: 8 },
  tileK: { color: C.faint, fontFamily: MONO, fontSize: 9, fontWeight: "700", letterSpacing: 1 },
  tileV: { color: C.text, fontFamily: MONO, fontSize: 22, fontWeight: "700", marginTop: 4 },
  tileU: { color: C.dim, fontSize: 12 },
  tileN: { color: C.dim, fontSize: 10, marginTop: 2 },
  btn: { borderWidth: 1, borderColor: C.line2, backgroundColor: C.panel2, paddingVertical: 9, paddingHorizontal: 12, borderRadius: 2, alignItems: "center" },
  btnT: { color: C.text, fontFamily: MONO, fontWeight: "700", fontSize: 12, letterSpacing: 0.5 },
  mode: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 14, paddingVertical: 8, backgroundColor: C.bg2, borderBottomWidth: 1, borderColor: C.line },
  modeBadge: { borderWidth: 1, borderColor: C.WATCH, paddingHorizontal: 6, paddingVertical: 2, backgroundColor: "#d9b43a14" },
  modeBadgeT: { color: C.WATCH, fontFamily: MONO, fontSize: 9, fontWeight: "700", letterSpacing: 1 },
  modeT: { color: C.text, fontFamily: MONO, fontSize: 11 },
  axis: { color: C.faint, fontSize: 9, fontFamily: MONO },
  h1: { color: C.text, fontFamily: MONO, fontWeight: "700", fontSize: 18, letterSpacing: 1 },
  dim: { color: C.dim },
  faint: { color: C.faint, fontSize: 11 },
  row: { flexDirection: "row", alignItems: "center" },
  kvK: { color: C.faint, fontFamily: MONO, fontSize: 10, fontWeight: "700", letterSpacing: 1, marginTop: 8 },
  kvV: { color: C.text, fontSize: 14, marginTop: 2 },
  chip: { borderWidth: 1, borderColor: C.line2, paddingHorizontal: 6, paddingVertical: 2, marginRight: 4, marginBottom: 4 },
  chipT: { fontFamily: MONO, fontSize: 9, fontWeight: "700", color: C.dim },
});
