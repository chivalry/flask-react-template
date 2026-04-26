import { Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";

export default function App() {
  return (
    <>
      <nav
        style={{
          padding: "0.75rem 1.5rem",
          borderBottom: "1px solid #e0e0e0",
          display: "flex",
          gap: "1rem",
          alignItems: "center",
        }}
      >
        <Link to="/" style={{ fontWeight: 600, textDecoration: "none" }}>
          Flask React Template
        </Link>
      </nav>

      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </>
  );
}
