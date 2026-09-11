import { NavLink, Route, Routes } from "react-router-dom";
import { EthicsNotice } from "./components/EthicsNotice";
import { Catalog } from "./pages/Catalog";
import { Home } from "./pages/Home";
import { ReportPage } from "./pages/Report";

export default function App() {
  return (
    <div className="app-shell">
      <div className="fx-grid" aria-hidden />
      <div className="fx-scan" aria-hidden />
      <div className="fx-vignette" aria-hidden />
      <EthicsNotice />
      <header className="topbar">
        <NavLink to="/" className="brand">
          <div className="brand-mark">OD</div>
          <div>
            <h1>OSINT Desk</h1>
            <p>// local public-source node</p>
          </div>
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Lookup
          </NavLink>
          <NavLink to="/catalog">Catalog</NavLink>
          <span className="pill">no persist</span>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/scan/:jobId" element={<ReportPage />} />
        </Routes>
      </main>
    </div>
  );
}
