import { NavLink, Route, Routes } from "react-router-dom";
import Coach from "./pages/Coach";
import Dashboard from "./pages/Dashboard";
import Drills from "./pages/Drills";
import Errors from "./pages/Errors";
import InterviewRoom from "./pages/InterviewRoom";
import Jobs from "./pages/Jobs";
import NewInterview from "./pages/NewInterview";
import Profile from "./pages/Profile";
import Report from "./pages/Report";
import Settings from "./pages/Settings";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/interviews/new", label: "New interview" },
  { to: "/errors", label: "Errors" },
  { to: "/drills", label: "Drills" },
  { to: "/profile", label: "Profile" },
  { to: "/jobs", label: "Jobs" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  return (
    <div className="layout">
      <nav className="sidebar">
        <h1>Interview Trainer</h1>
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"}>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/interviews/new" element={<NewInterview />} />
          <Route path="/interviews/:sessionId" element={<InterviewRoom />} />
          <Route path="/interviews/:sessionId/report" element={<Report />} />
          <Route path="/interviews/:sessionId/coach" element={<Coach />} />
          <Route path="/errors" element={<Errors />} />
          <Route path="/drills" element={<Drills />} />
          <Route path="/profile" element={<Profile />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
