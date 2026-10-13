import { createBrowserRouter, Link, RouterProvider } from "react-router";
import { Layout } from "./components/Layout";
import { KnowledgePage } from "./pages/KnowledgePage";
import { LabPage } from "./pages/LabPage";
import { MemoryPage } from "./pages/MemoryPage";
import { RubricPage } from "./pages/RubricPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { StudioPage } from "./pages/StudioPage";
import { SystemPage } from "./pages/SystemPage";

function NotFound() {
  return (
    <div className="page">
      <div className="empty">
        <strong>Page not found</strong>
        <Link to="/">Back to the studio</Link>
      </div>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <StudioPage /> },
      { path: "/runs", element: <RunsPage /> },
      { path: "/runs/:id", element: <RunPage /> },
      { path: "/lab", element: <LabPage /> },
      { path: "/memory", element: <MemoryPage /> },
      { path: "/rubric", element: <RubricPage /> },
      { path: "/knowledge", element: <KnowledgePage /> },
      { path: "/system", element: <SystemPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}
