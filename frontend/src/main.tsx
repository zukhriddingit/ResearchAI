import { createRoot } from "react-dom/client";
import type { Root } from "react-dom/client";
import App from "./App";
import "./styles.css";

type RootElement = HTMLElement & { _deepPaperRoot?: Root };

const rootElement = document.getElementById("root") as RootElement;
const root = rootElement._deepPaperRoot ?? createRoot(rootElement);
rootElement._deepPaperRoot = root;
root.render(<App />);
