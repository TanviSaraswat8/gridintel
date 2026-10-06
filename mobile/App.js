import React, { useEffect, useRef, useState } from "react";
import { Animated, BackHandler, Pressable, StatusBar, View } from "react-native";
import { Text, useLang } from "./src/i18n";
import { api, setOnUnauthorized, setToken } from "./src/api";
import {
  AlertsScreen, AnalyticsScreen, GridScreen, HomeScreen, InvestigationScreen, LoginScreen, ProfileScreen, ScadaScreen, SubstationScreen,
} from "./src/screens";
import { C, MONO, ModeBanner, riskColor, tsFmt } from "./src/ui";

const TABS = [{ key: "home", label: "HOME" }, { key: "grid", label: "GRID" }, { key: "alerts", label: "ALERTS" }, { key: "analytics", label: "ANALYTICS" }];
const TITLES = { home: "Command Center", grid: "Substations", alerts: "Alerts", analytics: "Analytics", substation: "Substation detail",
  investigation: "Investigation", scada: "SCADA", profile: "Profile / System" };

function Splash({ onDone }) {
  const o = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(o, { toValue: 1, duration: 700, useNativeDriver: true }).start();
    const t = setTimeout(onDone, 1400);
    return () => clearTimeout(t);
  }, []);
  return (
    <View style={{ flex: 1, backgroundColor: C.bg, alignItems: "center", justifyContent: "center" }}>
      <Animated.View style={{ opacity: o, alignItems: "center" }}>
        <Text noTranslate style={{ color: C.text, fontFamily: MONO, fontSize: 26, fontWeight: "700", letterSpacing: 6 }}>GRID<Text style={{ color: C.accent }}>INTEL</Text></Text>
        <Text style={{ color: C.dim, marginTop: 10 }}>AI grid intelligence · field engineering</Text>
        <Text style={{ color: C.faint, marginTop: 30, fontSize: 11 }}>Decision support · not a certified protection system</Text>
      </Animated.View>
    </View>
  );
}

export default function App() {
  const lang = useLang(); // re-mount the visible tree when the language changes
  const [splash, setSplash] = useState(true);
  const [user, setUser] = useState(null);
  const [stack, setStack] = useState([{ name: "home", params: {} }]);
  const [sid, setSid] = useState("220-sec-46");
  const [status, setStatus] = useState(null);
  const [tick, setTick] = useState(0);
  const [banner, setBanner] = useState(null);
  const lastAlert = useRef(null);
  const lastKey = useRef("");

  const top = stack[stack.length - 1];
  const nav = (name, params = {}) => setStack((s) => [...s, { name, params }]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const tab = (name) => setStack([{ name, params: {} }]);
  const logout = () => { setToken(null); setUser(null); setStack([{ name: "home", params: {} }]); lastAlert.current = null; };

  useEffect(() => { setOnUnauthorized(logout); }, []);
  useEffect(() => {
    const h = BackHandler.addEventListener("hardwareBackPress", () => { if (stack.length > 1) { back(); return true; } return false; });
    return () => h.remove();
  }, [stack]);

  // poll replay status → refresh screens on cursor change; in-app alert banner for new alerts
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const run = async () => {
      try {
        const st = await api.get("/replay/status");
        if (!alive) return;
        setStatus(st);
        const key = `${st.cursor}|${st.mode}`;
        if (key !== lastKey.current) { lastKey.current = key; setTick((t) => t + 1); }
        const alerts = st.recent_events.filter((e) => e.type === "ALERT");
        const newest = alerts[alerts.length - 1];
        if (lastAlert.current === null) lastAlert.current = newest ? newest.alert_id : 0;
        else if (newest && newest.alert_id > lastAlert.current) {
          lastAlert.current = newest.alert_id;
          setBanner(newest);
          setTimeout(() => setBanner((b) => (b && b.alert_id === newest.alert_id ? null : b)), 10000);
        }
      } catch (e) { /* keep last state */ }
    };
    run();
    const id = setInterval(run, 1500);
    return () => { alive = false; clearInterval(id); };
  }, [user]);

  if (splash) return <><StatusBar barStyle="light-content" backgroundColor={C.bg} /><Splash onDone={() => setSplash(false)} /></>;
  if (!user) return <View key={lang} style={{ flex: 1, backgroundColor: C.bg }}><StatusBar barStyle="light-content" backgroundColor={C.bg} /><LoginScreen onLogin={setUser} /></View>;

  const common = { tick, sid, setSid, nav, status, user, params: top.params };
  const screen = {
    home: <HomeScreen {...common} />, grid: <GridScreen {...common} />, alerts: <AlertsScreen {...common} />,
    analytics: <AnalyticsScreen {...common} />, substation: <SubstationScreen {...common} />, investigation: <InvestigationScreen {...common} />,
    scada: <ScadaScreen {...common} />, profile: <ProfileScreen user={user} onLogout={logout} />,
  }[top.name];
  const activeTab = stack[0].name;

  return (
    <View key={lang} style={{ flex: 1, backgroundColor: C.bg }}>
      <StatusBar barStyle="light-content" backgroundColor={C.bg} />
      <View style={{ paddingTop: 38, paddingHorizontal: 14, paddingBottom: 10, flexDirection: "row", alignItems: "center", backgroundColor: "#0b1016", borderBottomWidth: 1, borderColor: C.line }}>
        {stack.length > 1 ? <Pressable onPress={back} hitSlop={12} style={{ marginRight: 12 }}><Text style={{ color: C.accent, fontSize: 24 }}>‹</Text></Pressable> : null}
        <View style={{ flex: 1 }}>
          <Text noTranslate style={{ color: C.text, fontFamily: MONO, fontWeight: "700", letterSpacing: 3, fontSize: 13 }}>GRID<Text style={{ color: C.accent }}>INTEL</Text></Text>
          <Text style={{ color: C.dim, fontSize: 11 }}>{TITLES[top.name]}</Text>
        </View>
        <Pressable onPress={() => nav("profile")} hitSlop={10} style={{ borderWidth: 1, borderColor: C.line2, borderRadius: 14, width: 28, height: 28, alignItems: "center", justifyContent: "center" }}>
          <Text style={{ color: C.text, fontFamily: MONO, fontSize: 12 }}>{(user.username || "?")[0].toUpperCase()}</Text>
        </Pressable>
      </View>
      <ModeBanner status={status} />
      {banner ? (
        <Pressable onPress={() => { setBanner(null); nav("investigation", { sid: banner.substation_id, ts: banner.timestamp }); }}
          style={{ margin: 10, marginBottom: 0, padding: 12, backgroundColor: C.panel2, borderLeftWidth: 4, borderLeftColor: riskColor(banner.risk_category), borderWidth: 1, borderColor: C.line2, borderRadius: 8 }}>
          <Text style={{ color: riskColor(banner.risk_category), fontFamily: MONO, fontWeight: "700", fontSize: 11 }}>{banner.risk_category} · RISK {Math.round(banner.risk_score)}</Text>
          <Text style={{ color: C.text, marginTop: 3 }}>{banner.message}</Text>
          <Text style={{ color: C.dim, fontSize: 11, marginTop: 2 }}>{banner.parameter_label} · {tsFmt(banner.timestamp)} · tap to investigate</Text>
        </Pressable>
      ) : null}
      <View style={{ flex: 1 }}>{screen}</View>
      <View style={{ flexDirection: "row", borderTopWidth: 1, borderColor: C.line, backgroundColor: "#0b1016", paddingBottom: 18 }}>
        {TABS.map((t) => (
          <Pressable key={t.key} onPress={() => tab(t.key)} style={{ flex: 1, paddingVertical: 13, alignItems: "center", borderTopWidth: 2, borderTopColor: activeTab === t.key ? C.accent : "transparent" }}>
            <Text style={{ color: activeTab === t.key ? C.text : C.faint, fontFamily: MONO, fontSize: 10, fontWeight: "700", letterSpacing: 1.2 }}>{t.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
