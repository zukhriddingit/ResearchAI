import { FileUp, FlaskConical, Link, Loader2, Play } from "lucide-react";
import { ChangeEvent, FormEvent, useRef, useState } from "react";

interface Props {
  busy: boolean;
  onLoad: (sourceType: "arxiv_url" | "pdf_text" | "demo", source: string) => void;
  onUpload: (file: File) => void;
}

function UploadBar({ busy, onLoad, onUpload }: Props) {
  const [url, setUrl] = useState("https://arxiv.org/abs/2106.09685");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (url.trim()) onLoad("arxiv_url", url.trim());
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) onUpload(file);
    event.target.value = "";
  };

  return (
    <header className="topbar">
      <div className="brand-block">
        <div className="brand-mark">DP</div>
        <div>
          <h1>DeepPaper</h1>
          <p>Read one paper. Understand the whole field.</p>
        </div>
      </div>
      <form className="load-form" onSubmit={submit}>
        <label className="url-input">
          <Link size={16} />
          <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="arXiv URL" />
        </label>
        <button className="button secondary" type="submit" disabled={busy}>
          {busy ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
          <span>Load Paper</span>
        </button>
        <button className="button primary" type="button" disabled={busy} onClick={() => onLoad("demo", "lora")}>
          <FlaskConical size={16} />
          <span>LoRA Demo</span>
        </button>
        <input
          ref={fileInputRef}
          className="visually-hidden"
          type="file"
          accept="application/pdf,text/plain,text/markdown,.pdf,.txt,.md,.markdown,.tex"
          onChange={handleFileChange}
        />
        <button className="button secondary" type="button" disabled={busy} onClick={() => fileInputRef.current?.click()}>
          {busy ? <Loader2 className="spin" size={16} /> : <FileUp size={16} />}
          <span>Upload Paper</span>
        </button>
      </form>
    </header>
  );
}

export default UploadBar;
