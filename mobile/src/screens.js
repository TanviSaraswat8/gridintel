import React, { useCallback, useEffect, useState } from "react";
import { Pressable, RefreshControl, ScrollView, Text, TextInput, View } from "react-native";
import { api, getBase, setBase, setToken } from "./api";
import { Badge, Btn, C, Columns, ErrorBox, Loading, MONO, Panel, Tile, fmt, hourFmt, riskColor, riskFill, s, tsFmt } from "./ui";

const DISCLAIMER = "Prototype AI risk classification — not certified protection thresholds. Risk scores and anomaly alerts are model-generated decision-support indicators, not certified protection or fault-diagnosis outputs.";

function useData(loader, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setData(await loader()); setError(null); } catch (e) { setError(e.message); }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  const refresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };
  return { data, error, refreshing, refresh };
}

const Scroll = ({ children, refreshing, onRefresh }) => (
  <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12, paddingBottom: 30 }}
    refreshControl={onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} tintColor={C.accent} /> : undefined}>
    {children}
  </ScrollView>
);
const Guard = ({ error, data, refresh, children }) =>
  error && !data ? <Scroll><ErrorBox error={error} onRetry={refresh} /></Scroll> : !data ? <Loading /> : children;

function Cards({ cards }) {
  const b = cards.breaker_state;
  const ab = Object.keys(b.abnormal || {});
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }}>
      <Tile label="VOLTAGE" value={fmt(cards.voltage.value, 1)} unit={cards.voltage.unit} name={cards.voltage.name} />
      <Tile label="CURRENT" value={fmt(cards.current.value, 0)} unit={cards.current.unit} name={cards.current.name} />
      <Tile label="LOAD" value={fmt(cards.transformer_load.value, 2)} unit={cards.transformer_load.unit} name={cards.transformer_load.name} />
      <Tile label="TEMPERATURE" value={fmt(cards.transformer_temperature.value, 0)} unit="°C" name={cards.transformer_temperature.name} />
      <Tile label="FEEDER LOAD Σ" value={fmt(cards.feeder_load.value, 0)} unit="A" name={cards.feeder_load.name} />
      <Tile label="BREAKER STATE" flag={ab.length > 0} unit=""
        value={Object.entries(b.counts).map(([k, v]) => `${k === "AUTO_ON" ? "AUTO" : k} ${v}`).join(" ") || "—"}
        name={ab.length ? `${ab.length} PTW / breakdown` : "no PTW / breakdown"} />
    </View>
  );
}

export function AlertCard({ a, nav }) {
  const col = riskColor(a.risk_category);
  return (
    <View style={{ backgroundColor: C.panel, borderWidth: 1, borderColor: C.line, borderLeftWidth: 4, borderLeftColor: col, borderRadius: 8, padding: 12, marginBottom: 10 }}>
      <View style={[s.row, { justifyContent: "space-between" }]}>
        <Text style={{ color: col, fontFamily: MONO, fontWeight: "700", letterSpacing: 1.5, fontSize: 12 }}>{a.risk_category}</Text>
        <Text style={[s.faint, { fontFamily: MONO }]}>{tsFmt(a.record_timestamp)}</Text>
      </View>
      <Text style={{ color: C.text, fontWeight: "700", fontSize: 16, marginTop: 6 }}>{a.substation_name}</Text>
      <Text style={[s.dim, { marginTop: 2 }]}>"Potential abnormal operating condition"</Text>
      <Text style={[s.faint, { marginTop: 2 }]} numberOfLines={1}>{a.parameter_label}{a.equipment ? ` · ${a.equipment}` : ""}</Text>
      <View style={[s.row, { justifyContent: "space-between", marginTop: 10 }]}>
        <Text style={{ color: C.text, fontFamily: MONO }}>Risk <Text style={{ color: col, fontWeight: "700", fontSize: 18 }}>{fmt(a.risk_score, 0)}</Text>
          <Text style={s.faint}>  conf {fmt(a.confidence, 0)}%</Text></Text>
        <Btn title="INVESTIGATE" kind="primary" onPress={() => nav("investigation", { sid: a.substation_id, ts: a.record_timestamp })} />
      </View>
    </View>
  );
}

// -------------------------------------------------------------------------------------------- LOGIN
export function LoginScreen({ onLogin }) {
  const [server, setServer] = useState(getBase());
  const [user, setUser] = useState("operator");
  const [pass, setPass] = useState("hvpnl2026");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      setBase(server);
      const r = await api.post("/auth/login", { username: user.trim(), password: pass });
      setToken(r.access_token);
      onLogin(r.user);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const input = { borderWidth: 1, borderColor: C.line2, backgroundColor: C.bg2, color: C.text, padding: 12, fontFamily: MONO, marginTop: 4, marginBottom: 12, borderRadius: 6 };
  return (
    <ScrollView contentContainerStyle={{ padding: 22, paddingTop: 70 }} keyboardShouldPersistTaps="handled">
      <Text style={[s.h1, { fontSize: 24, letterSpacing: 5 }]}>GRID<Text style={{ color: C.accent }}>INTEL</Text></Text>
      <Text style={[s.dim, { marginTop: 8, marginBottom: 28 }]}>Field engineering app · AI grid intelligence for substation monitoring</Text>
      <Panel title="SIGN IN">
        <Text style={s.kvK}>API SERVER</Text>
        <TextInput style={input} value={server} onChangeText={setServer} autoCapitalize="none" autoCorrect={false} placeholder="http://192.168.x.x:8000" placeholderTextColor={C.faint} />
        <Text style={s.kvK}>USERNAME</Text>
        <TextInput style={input} value={user} onChangeText={setUser} autoCapitalize="none" autoCorrect={false} />
        <Text style={s.kvK}>PASSWORD</Text>
        <TextInput style={input} value={pass} onChangeText={setPass} secureTextEntry />
        {err ? <Text style={{ color: "#ff8c8c", marginBottom: 10 }}>{err}</Text> : null}
        <Btn title={busy ? "SIGNING IN…" : "SIGN IN"} kind="primary" onPress={go} disabled={busy} />
      </Panel>
      <Text style={s.faint}>Demo: operator / hvpnl2026. Phone and API must be on the same network (or use the deployed API URL).</Text>
    </ScrollView>
  );
}

// -------------------------------------------------------------------------------------------- HOME (command center)
export function HomeScreen({ tick, nav, setSid, status, user }) {
  const { data, error, refreshing, refresh } = useData(() => Promise.all([api.get("/command-center"), api.get("/investigations/demo")]), [tick]);
  const isOp = ["OPERATOR", "ENGINEER", "ADMIN"].includes(user?.role);
  const ctl = async (a) => { try { await api.post(`/replay/${a}`); refresh(); } catch (e) {} };
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (() => {
        const [cc, demo] = data;
        const hcol = cc.grid_health == null ? C.dim : riskFill(100 - cc.grid_health);
        return (
          <Scroll refreshing={refreshing} onRefresh={refresh}>
            <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }}>
              <Tile label="GRID HEALTH" value={cc.grid_health == null ? "—" : `${fmt(cc.grid_health, 1)}%`} unit="" name="100 − mean AI risk" />
              <Tile label="ACTIVE SUBSTATIONS" value={`${cc.active_substations}/${cc.sheets_total}`} unit="" name="with source readings" />
              <Tile label="ACTIVE ALERTS" value={String(cc.active_alerts)} unit="" name="this replay" flag={cc.active_alerts > 0} />
              <Tile label="HIGH-RISK EVENTS" value={String(cc.high_risk_events)} unit="" name="HIGH RISK + CRITICAL" flag={cc.high_risk_events > 0} />
            </View>
            <Panel title="MODEL STATUS" hint={cc.model_version}>
              <Text style={{ color: C.NORMAL, fontFamily: MONO, fontWeight: "700" }}>● {cc.model_status}</Text>
            </Panel>
            <Panel title="SUBSTATIONS NOW" hint={tsFmt(cc.replay.timestamp)}>
              {cc.substations.map((x) => (
                <Pressable key={x.substation_id} onPress={() => { setSid(x.substation_id); nav("substation", { sid: x.substation_id }); }}
                  style={[s.row, { justifyContent: "space-between", paddingVertical: 9, borderBottomWidth: 1, borderColor: C.line }]}>
                  <Text style={{ color: C.text, fontFamily: MONO, fontWeight: "700" }}>{x.name}</Text>
                  {x.available ? <View style={s.row}><Text style={{ color: riskColor(x.risk_category), fontFamily: MONO, marginRight: 8 }}>{fmt(x.risk_score, 0)}</Text><Badge cat={x.risk_category} small /></View>
                    : <Text style={s.faint}>no record yet</Text>}
                </Pressable>
              ))}
            </Panel>
            <Panel title="DEMO INVESTIGATIONS" hint="real recorded events">
              {demo.items.map((d) => (
                <Pressable key={d.id} onPress={() => nav("investigation", { sid: d.substation_id, ts: d.timestamp })} style={{ paddingVertical: 8, borderBottomWidth: 1, borderColor: C.line }}>
                  <View style={[s.row, { justifyContent: "space-between" }]}><Badge cat={d.risk_category} small /><Text style={[s.faint, { fontFamily: MONO }]}>{tsFmt(d.timestamp)}</Text></View>
                  <Text style={{ color: C.text, marginTop: 4, fontWeight: "600" }}>{d.title}</Text>
                </Pressable>
              ))}
            </Panel>
            <Panel title="REPLAY CONTROL" hint={status ? `${status.cursor + 1}/${status.total} · ${status.speed}x · ${status.mode}` : ""}>
              {isOp ? (
                <View style={[s.row, { gap: 6 }]}>
                  <Btn title="▶ START" kind="go" style={{ flex: 1 }} onPress={() => ctl("start")} />
                  <Btn title="❚❚" style={{ flex: 0.6 }} onPress={() => ctl("pause")} />
                  <Btn title="NEXT" style={{ flex: 1 }} onPress={() => ctl("next")} />
                </View>
              ) : <Text style={s.faint}>Replay control requires the OPERATOR role.</Text>}
            </Panel>
            <Text style={[s.panelTitle, { marginVertical: 8 }]}>LATEST ALERTS</Text>
            {cc.recent_alerts.length ? cc.recent_alerts.slice(0, 3).map((a) => <AlertCard key={a.id} a={a} nav={nav} />) : <Text style={s.faint}>No alerts yet — start the replay.</Text>}
          </Scroll>
        );
      })() : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- GRID (substations)
export function GridScreen({ tick, nav, setSid }) {
  const { data, error, refreshing, refresh } = useData(() => api.get("/fleet", { sort: "risk" }), [tick]);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (
        <Scroll refreshing={refreshing} onRefresh={refresh}>
          {data.items.map((x) => x.available ? (
            <Pressable key={x.substation_id} onPress={() => { setSid(x.substation_id); nav("substation", { sid: x.substation_id }); }}
              style={{ backgroundColor: C.panel, borderWidth: 1, borderColor: C.line, borderLeftWidth: 3, borderLeftColor: riskColor(x.risk_category), borderRadius: 8, padding: 12, marginBottom: 8 }}>
              <View style={[s.row, { justifyContent: "space-between" }]}>
                <Text style={{ color: C.text, fontFamily: MONO, fontWeight: "700", fontSize: 15 }}>{x.name}</Text>
                <Text style={{ color: riskColor(x.risk_category), fontFamily: MONO, fontWeight: "700", fontSize: 18 }}>{fmt(x.risk_score, 0)}</Text>
              </View>
              <View style={[s.row, { justifyContent: "space-between", marginTop: 6 }]}>
                <Badge cat={x.risk_category} small />
                <Text style={s.faint}>V {fmt(x.voltage_health, 0)} · L {fmt(x.load_health, 0)} · T {x.temperature_health == null ? "n/a" : fmt(x.temperature_health, 0)}</Text>
              </View>
            </Pressable>
          ) : (
            <View key={x.substation_id} style={{ paddingVertical: 8, paddingHorizontal: 12, borderBottomWidth: 1, borderColor: C.line, flexDirection: "row", justifyContent: "space-between" }}>
              <Text style={{ color: C.dim, fontFamily: MONO }}>{x.name}</Text><Text style={[s.faint, { fontFamily: MONO, fontSize: 10 }]}>NO SOURCE READINGS</Text>
            </View>
          ))}
        </Scroll>
      ) : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- SUBSTATION DETAIL
export function SubstationScreen({ tick, params, nav }) {
  const { data, error, refreshing, refresh } = useData(() => api.get(`/substations/${params.sid}`), [params.sid, tick]);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (() => {
        const r = data.current;
        if (!data.available || !r?.available) return <Scroll><Panel title={data.substation.name}><Text style={s.dim}>NO DATA AVAILABLE — no record at the current replay time.</Text></Panel></Scroll>;
        const n = Math.min(24, data.series.timestamps.length), lbl = data.series.timestamps.slice(-n).map(hourFmt);
        return (
          <Scroll refreshing={refreshing} onRefresh={refresh}>
            <Panel style={{ borderLeftWidth: 4, borderLeftColor: riskColor(r.risk_category) }}>
              <Text style={s.h1}>{data.substation.name.toUpperCase()}</Text>
              <View style={[s.row, { justifyContent: "space-between", marginTop: 8 }]}>
                <Badge cat={r.risk_category} />
                <Text style={{ color: C.text, fontFamily: MONO }}>risk {fmt(r.risk_score, 0)} · conf {fmt(r.confidence, 0)}%</Text>
              </View>
              <Text style={[s.faint, { marginTop: 6 }]}>{tsFmt(r.timestamp)} · historical replay · {data.substation.validation}</Text>
              <View style={[s.row, { gap: 6, marginTop: 10 }]}>
                <Btn title="SCADA" style={{ flex: 1 }} onPress={() => nav("scada", { sid: params.sid })} />
                <Btn title="INVESTIGATE" kind="primary" style={{ flex: 1 }} onPress={() => nav("investigation", { sid: params.sid, ts: r.timestamp })} />
              </View>
            </Panel>
            <Cards cards={r.cards} />
            <Panel title="RISK HISTORY" hint={`last ${n} hours`}><Columns values={data.series.risk.slice(-n)} labels={lbl} colorFn={riskFill} /></Panel>
            <Panel title="TRANSFORMERS"><Text style={{ color: C.text, fontFamily: MONO }}>{data.transformers.join("   ")}</Text></Panel>
            <Text style={[s.panelTitle, { marginVertical: 8 }]}>RECENT ALERTS</Text>
            {data.alerts.length ? data.alerts.slice(0, 4).map((a) => <AlertCard key={a.id} a={a} nav={nav} />) : <Text style={s.faint}>No alerts for this substation in this replay.</Text>}
          </Scroll>
        );
      })() : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- SCADA
export function ScadaScreen({ tick, params, sid }) {
  const id = params?.sid || sid;
  const { data, error, refreshing, refresh } = useData(() => Promise.all([api.get("/scada/latest", { substation: id }), api.get("/scada/history", { substation: id, upto_cursor: true, last: 24 })]), [id, tick]);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (() => {
        const [lat, h] = data, r = lat.record, lbl = h.timestamps.map(hourFmt), sg = h.signals;
        const series = [["VOLTAGE", sg.voltages[0], C.accent], ["LOAD", sg.transformer_loads[0], "#8fd3a6"], ["CURRENT Σ FEEDERS", sg.feeder_total[0], "#6fb4ff"],
          ["TEMPERATURE", sg.transformer_temperature[0] || sg.oil_temperature[0], "#f0c06a"]];
        return (
          <Scroll refreshing={refreshing} onRefresh={refresh}>
            <View style={[s.row, { gap: 6, marginBottom: 10 }]}>
              <View style={[s.chip, { opacity: 0.5 }]}><Text style={s.chipT}>LIVE · NOT CONNECTED</Text></View>
              <View style={[s.chip, { borderColor: C.WATCH }]}><Text style={[s.chipT, { color: C.WATCH }]}>HISTORICAL REPLAY</Text></View>
            </View>
            {r?.available ? <Cards cards={r.cards} /> : <Panel><Text style={s.dim}>No record at the current replay time.</Text></Panel>}
            {series.map(([t, x, col]) => x ? (
              <Panel key={t} title={t} hint={`${x.name} · ${x.unit}`}><Columns values={x.values} labels={lbl} unit={x.unit} color={col} /></Panel>
            ) : null)}
            {r?.available ? (
              <Panel title="BREAKER / CIRCUIT STATE">
                <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
                  {r.states.filter((x) => x.state !== "CLEAR").map((x, i) => {
                    const col = x.state === "BREAKDOWN" ? C["HIGH RISK"] : x.state === "PTW" ? C.WATCH : x.state === "ON" || x.state === "AUTO_ON" ? C.NORMAL : C.line2;
                    return <View key={i} style={[s.chip, { borderColor: col }]}><Text style={[s.chipT, { color: col === C.line2 ? C.dim : col }]}>{x.name}: {x.state}</Text></View>;
                  })}
                </View>
              </Panel>
            ) : null}
          </Scroll>
        );
      })() : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- ALERTS
export function AlertsScreen({ tick, nav }) {
  const [scope, setScope] = useState("replay");
  const { data, error, refreshing, refresh } = useData(() => (scope === "replay" ? api.get("/alerts") : api.get("/anomalies", { min_risk: 56, size: 50 })), [tick, scope]);
  return (
    <Scroll refreshing={refreshing} onRefresh={refresh}>
      <View style={[s.row, { gap: 6, marginBottom: 10 }]}>
        <Btn title="THIS REPLAY" kind={scope === "replay" ? "primary" : undefined} style={{ flex: 1 }} onPress={() => setScope("replay")} />
        <Btn title="FULL HISTORY" kind={scope === "history" ? "primary" : undefined} style={{ flex: 1 }} onPress={() => setScope("history")} />
      </View>
      {error && !data ? <ErrorBox error={error} onRetry={refresh} /> : !data ? <Loading /> :
        data.items.length ? data.items.map((a, i) => <AlertCard key={a.id || i} a={a} nav={nav} />) : <Text style={s.faint}>No alerts yet. Start the replay from Home.</Text>}
      <Text style={[s.faint, { marginTop: 6 }]}>Alerts indicate a potential abnormal operating condition, not a confirmed fault.</Text>
    </Scroll>
  );
}

// -------------------------------------------------------------------------------------------- INVESTIGATION
export function InvestigationScreen({ params }) {
  const { data, error, refresh } = useData(() => api.get("/investigations", { substation: params.sid, timestamp: params.ts }), [params.sid, params.ts]);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (() => {
        const col = riskColor(data.risk_category), p = data.primary || {}, t = data.trend, ps = t.series[0];
        const maxS = Math.max(...data.contributing_signals.map((x) => x.contribution_share), 0.01);
        const lvl = { High: C.WARNING, Moderate: C.WATCH, Low: C.dim };
        return (
          <Scroll>
            <Panel style={{ borderLeftWidth: 4, borderLeftColor: col }}>
              <Text style={{ color: C.accent, fontFamily: MONO, fontWeight: "700", letterSpacing: 2, fontSize: 11 }}>● AI INVESTIGATION</Text>
              <Text style={{ color: col, fontFamily: MONO, fontWeight: "700", letterSpacing: 2, marginTop: 8 }}>{data.title}</Text>
              <Text style={[s.h1, { marginTop: 4 }]}>{data.substation.name}</Text>
              <Text style={[s.dim, { marginTop: 4 }]}>"{data.headline}"</Text>
              <View style={[s.row, { justifyContent: "space-between", marginTop: 12 }]}>
                <View><Text style={s.kvK}>RISK</Text><Text style={{ color: col, fontFamily: MONO, fontWeight: "700", fontSize: 30 }}>{fmt(data.risk_score, 0)}<Text style={{ fontSize: 13, color: C.faint }}>/100</Text></Text></View>
                <View><Text style={s.kvK}>CONFIDENCE</Text><Text style={{ color: C.text, fontFamily: MONO, fontWeight: "700", fontSize: 30 }}>{fmt(data.confidence, 0)}%</Text></View>
              </View>
              <Text style={[s.faint, { marginTop: 4 }]}>{tsFmt(data.timestamp)} · {data.evaluation} · {data.model_key}</Text>
            </Panel>
            <Panel title="WHAT HAPPENED"><Text style={s.kvV}>{data.what}</Text>
              <Text style={s.kvK}>PARAMETER</Text><Text style={s.kvV}>{p.base_parameter}</Text>
              <Text style={s.kvK}>CURRENT VALUE</Text><Text style={[s.kvV, { fontFamily: MONO, fontSize: 18 }]}>{fmt(data.current_value, 2)} {p.unit}</Text>
              <Text style={s.kvK}>EXPECTED</Text><Text style={s.kvV}>{data.expected_behaviour}</Text></Panel>
            <Panel title="WHY IT WAS FLAGGED"><Text style={s.kvV}>{data.why}</Text><Text style={s.kvK}>HOW UNUSUAL</Text><Text style={s.kvV}>{data.how_unusual}</Text></Panel>
            <Panel title="CONTRIBUTING SIGNALS" hint="not confirmed causes">
              {data.rules.map((r, i) => (
                <View key={"r" + i} style={{ paddingVertical: 8, borderBottomWidth: 1, borderColor: C.line }}>
                  <Text style={{ color: C.WARNING, fontFamily: MONO, fontSize: 10, fontWeight: "700" }}>ENGINEERING RULE {r.rule}</Text>
                  <Text style={{ color: C.text, fontWeight: "700", marginTop: 2 }}>{r.title}</Text><Text style={[s.dim, { fontSize: 12 }]}>{r.message}</Text>
                </View>))}
              {data.contributing_signals.slice(0, 5).map((x, i) => (
                <View key={i} style={{ paddingVertical: 8, borderBottomWidth: 1, borderColor: C.line }}>
                  <View style={[s.row, { justifyContent: "space-between" }]}>
                    <Text style={{ color: lvl[x.level], fontFamily: MONO, fontWeight: "700", fontSize: 10 }}>{x.level.toUpperCase()}</Text>
                    <Text style={{ color: C.text, fontFamily: MONO, fontSize: 12 }}>{fmt(x.value, 2)} {x.unit}</Text>
                  </View>
                  <Text style={{ color: C.text, fontWeight: "700", marginTop: 2 }}>{x.label}</Text>
                  <Text style={[s.dim, { fontSize: 12 }]}>{x.observed}</Text>
                  <View style={{ height: 6, backgroundColor: C.bg2, marginTop: 5, borderRadius: 3 }}><View style={{ height: 6, borderRadius: 3, width: `${(x.contribution_share / maxS) * 100}%`, backgroundColor: C.accent }} /></View>
                </View>))}
            </Panel>
            {ps ? <Panel title="TREND" hint={`${ps.name} · dashed = baseline`}><Columns values={ps.values} labels={t.timestamps.map(hourFmt)} baseline={ps.baseline_median} unit={ps.unit} /></Panel> : null}
            <Panel title="RISK AROUND THE EVENT"><Columns values={t.risk} labels={t.timestamps.map(hourFmt)} colorFn={riskFill} /></Panel>
            <Panel title="WHAT TO INVESTIGATE">{data.investigate.map((x, i) => <Text key={i} style={[s.kvV, { marginBottom: 6 }]}>• {x}</Text>)}</Panel>
            <Panel title="EVIDENCE" hint="source measurements">
              {data.evidence.slice(0, 8).map((e, i) => (
                <View key={i} style={[s.row, { justifyContent: "space-between", paddingVertical: 5, borderBottomWidth: 1, borderColor: C.line }]}>
                  <Text style={{ color: C.text, flex: 1, fontSize: 12 }} numberOfLines={1}>{e.name}</Text>
                  <Text style={{ color: C.text, fontFamily: MONO, fontSize: 12 }}>{fmt(e.value, 2)} {e.unit}  <Text style={s.faint}>med {fmt(e.median, 1)}</Text></Text>
                </View>))}
            </Panel>
            <Text style={[s.faint, { lineHeight: 16 }]}>{data.method}{"\n\n"}{DISCLAIMER}</Text>
          </Scroll>
        );
      })() : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- ANALYTICS
export function AnalyticsScreen({ sid, setSid }) {
  const { data, error, refresh } = useData(() => Promise.all([api.get("/analytics", { substation: sid }), api.get("/fleet")]), [sid]);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (() => {
        const [a, fl] = data, n = a.series.timestamps.length, lbl = a.series.timestamps.map(hourFmt), ev = a.evaluation || {};
        return (
          <Scroll>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              {fl.items.filter((x) => x.available).map((x) => (
                <Pressable key={x.substation_id} onPress={() => setSid(x.substation_id)}
                  style={[s.chip, { paddingVertical: 6, paddingHorizontal: 10, borderColor: x.substation_id === sid ? C.accent : C.line2 }]}>
                  <Text style={[s.chipT, { color: x.substation_id === sid ? C.text : C.dim, fontSize: 11 }]}>{x.name}</Text>
                </Pressable>))}
            </ScrollView>
            <Panel title="RISK DISTRIBUTION" hint={`${n} hourly records`}>
              {Object.entries(a.risk_distribution).map(([c, v]) => (
                <View key={c} style={[s.row, { marginVertical: 4 }]}>
                  <Text style={{ width: 86, color: riskColor(c), fontFamily: MONO, fontSize: 10 }}>{c}</Text>
                  <View style={{ flex: 1, height: 8, backgroundColor: C.bg2, borderRadius: 4 }}><View style={{ height: 8, borderRadius: 4, width: `${(v / n) * 100}%`, backgroundColor: riskColor(c) }} /></View>
                  <Text style={{ width: 28, textAlign: "right", color: C.text, fontFamily: MONO, fontSize: 11 }}>{v}</Text>
                </View>))}
            </Panel>
            <Panel title="ANOMALY TREND"><Columns values={a.series.anomaly} labels={lbl} colorFn={riskFill} /></Panel>
            {a.series.signals.transformer_loads[0] ? <Panel title="LOADING TREND" hint={a.series.signals.transformer_loads[0].name}><Columns values={a.series.signals.transformer_loads[0].values} labels={lbl} color="#8fd3a6" /></Panel> : null}
            <Panel title="TOP CONTRIBUTING SIGNALS">
              {a.top_contributing_signals.slice(0, 6).map((x, i) => <Text key={i} style={[s.kvV, { fontSize: 12 }]}>{i + 1}. {x.label}</Text>)}
            </Panel>
            <Panel title="UNSUPERVISED EVALUATION" hint="no labels → no accuracy">
              <Text style={s.kvV}>{ev.validation}</Text>
              <Text style={[s.faint, { marginTop: 4 }]}>Seed stability ρ {fmt(ev.seed_stability_spearman, 3)} · out-of-sample vs in-sample ρ {fmt(ev.lodo_vs_in_sample_spearman, 3)}</Text>
            </Panel>
          </Scroll>
        );
      })() : null}
    </Guard>
  );
}

// -------------------------------------------------------------------------------------------- PROFILE
export function ProfileScreen({ user, onLogout }) {
  const { data, error, refresh } = useData(() => api.get("/models"), []);
  return (
    <Guard error={error} data={data} refresh={refresh}>
      {data ? (
        <Scroll>
          <Panel title="PROFILE"><Text style={s.kvK}>USER</Text><Text style={s.kvV}>{user?.display_name || user?.username}</Text>
            <Text style={s.kvK}>ROLE</Text><Text style={s.kvV}>{user?.role}</Text><Text style={s.kvK}>API</Text><Text style={s.kvV}>{getBase()}</Text></Panel>
          <Panel title="SYSTEM">
            <Text style={s.kvK}>MODEL</Text><Text style={s.kvV}>{data.ensemble.name} (Isolation Forest · autoencoder · temporal AE · rules)</Text>
            <Text style={s.kvK}>DATA</Text><Text style={s.kvV}>HVPNL Faridabad SCADA daily logs — 02, 10, 27 Feb 2026</Text>
            <Text style={s.kvK}>VALIDATION</Text><Text style={s.kvV}>{data.ensemble.validation}</Text>
            <Text style={s.kvK}>MODE</Text><Text style={s.kvV}>Historical replay · live ingestion not connected</Text>
          </Panel>
          <Panel title="RISK CLASSIFICATION">
            {data.categories.map((c) => <View key={c.category} style={[s.row, { justifyContent: "space-between", paddingVertical: 3 }]}><Badge cat={c.category} small /><Text style={{ color: C.text, fontFamily: MONO }}>{c.min}–{c.max}</Text></View>)}
            <Text style={[s.faint, { marginTop: 6 }]}>{data.risk_note}</Text>
          </Panel>
          <Text style={[s.faint, { lineHeight: 16, marginBottom: 12 }]}>{DISCLAIMER}</Text>
          <Btn title="SIGN OUT" onPress={onLogout} />
        </Scroll>
      ) : null}
    </Guard>
  );
}
