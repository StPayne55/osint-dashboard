import { NavLink, Route, Routes } from "react-router-dom";
import { EthicsNotice } from "./components/EthicsNotice";
import { Catalog } from "./pages/Catalog";
import { Home } from "./pages/Home";
import { ReportPage } from "./pages/Report";

export default function App() {
  return (
    <div className="app-shell">
      <EthicsNotice />
      <header className="topbar">
        <NavLink to="/" className="brand">
          <div className="brand-mark">OD</div>
          <div>
            <h1>OSINT Desk</h1>
            <p>Local public-source lookup</p>
          </div>
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Lookup
          </NavLink>
          <NavLink to="/catalog">Catalog</NavLink>
          <span className="pill">no persistence</span>
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
