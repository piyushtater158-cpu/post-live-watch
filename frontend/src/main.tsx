import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import "./app.css";
import "./spa.css";
import { Layout } from "./components/Layout";
import CampaignEdit from "./pages/CampaignEdit";
import CampaignNew from "./pages/CampaignNew";
import Campaigns from "./pages/Campaigns";
import CreatorProfile from "./pages/CreatorProfile";
import Creators from "./pages/Creators";
import Decisions from "./pages/Decisions";
import Instagram from "./pages/Instagram";
import Intake from "./pages/Intake";
import Overview from "./pages/Overview";
import Queue from "./pages/Queue";
import Report from "./pages/Report";
import { AppStateProvider } from "./state";

function NotFound() {
  return (
    <main className="wrap">
      <div className="empty">
        <p>That page doesn't exist.</p>
        <small>
          <Link to="/">Back to the campaign overview</Link>
        </small>
      </div>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppStateProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/report" element={<Report />} />
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="/queue" element={<Queue />} />
            <Route path="/creators" element={<Creators />} />
            <Route path="/creators/:id" element={<CreatorProfile />} />
            <Route path="/decisions" element={<Decisions />} />
            <Route path="/intake" element={<Intake />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaigns/new" element={<CampaignNew />} />
            <Route path="/campaigns/:id/edit" element={<CampaignEdit />} />
            <Route path="/instagram" element={<Instagram />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppStateProvider>
  </StrictMode>,
);
