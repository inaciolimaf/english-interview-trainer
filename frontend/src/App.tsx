import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import Icon, { type IconName } from "./components/Icon";
import SystemStatus from "./components/SystemStatus";
import Coach from "./pages/Coach";
import Dashboard from "./pages/Dashboard";
import Drills from "./pages/Drills";
import Errors from "./pages/Errors";
import History from "./pages/History";
import InterviewRoom from "./pages/InterviewRoom";
import Jobs from "./pages/Jobs";
import NewInterview from "./pages/NewInterview";
import Profile from "./pages/Profile";
import Report from "./pages/Report";
import Settings from "./pages/Settings";

const NAV: { group: string; items: { to: string; label: string; icon: IconName }[] }[] = [
  {
    group: "Practice",
    items: [
      { to: "/", label: "Today", icon: "today" },
      { to: "/interviews/new", label: "New interview", icon: "new" },
      { to: "/drills", label: "Drills", icon: "drills" },
    ],
  },
  {
    group: "Review",
    items: [
      { to: "/interviews", label: "History", icon: "history" },
      { to: "/errors", label: "Errors", icon: "errors" },
    ],
  },
  {
    group: "Setup",
    items: [
      { to: "/profile", label: "Resume", icon: "resume" },
      { to: "/jobs", label: "Jobs", icon: "jobs" },
      { to: "/settings", label: "Settings", icon: "settings" },
    ],
  },
];

export default function App() {
  const location = useLocation();
  const [due, setDue] = useState(0);

  useEffect(() => {
    api.drillSummary().then((s) => setDue(s.due), () => {});
  }, [location.pathname]);

  return (
    <div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <nav className="rail" aria-label="Main">
        <NavLink to="/" className="wordmark" end>
          <span className="wordmark-name">Interview Trainer</span>
          <span className="wordmark-ipa ipa">/ˈɪntərvjuː ˈtreɪnər/</span>
        </NavLink>
        {NAV.map((section) => (
          <div key={section.group} className="rail-group">
            <span className="rail-heading">{section.group}</span>
            {section.items.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === "/" || item.to === "/interviews"}>
                <Icon name={item.icon} />
                <span>{item.label}</span>
                {item.to === "/drills" && due > 0 && (
                  <span className="rail-badge" aria-label={`${due} due`}>
                    {due}
                  </span>
                )}
              </NavLink>
            ))}
          </div>
        ))}
        <SystemStatus />
      </nav>
      <main className="main" id="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/interviews" element={<History />} />
          <Route path="/interviews/new" element={<NewInterview />} />
          <Route path="/interviews/:sessionId" element={<InterviewRoom />} />
          <Route path="/interviews/:sessionId/report" element={<Report />} />
          <Route path="/interviews/:sessionId/coach" element={<Coach />} />
          <Route path="/errors" element={<Errors />} />
          <Route path="/drills" element={<Drills />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}

function NotFound() {
  return (
    <section className="page narrow">
      <header className="page-head">
        <h1>Nothing here</h1>
      </header>
      <p className="soft">This address does not match any page. Use the menu to get back on track.</p>
    </section>
  );
}
