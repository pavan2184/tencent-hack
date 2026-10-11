"use client";

import { Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label, NativeSelect } from "@/components/ui/input";
import { uploadDocument } from "@/lib/api";
import { CLASSIFICATIONS, type Classification } from "@/lib/types";
import { useApiAction } from "@/lib/useApi";
import { ErrorState } from "./StateViews";

export function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [classification, setClassification] =
    useState<Classification>("internal");
  const upload = useApiAction(uploadDocument);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const formData = new FormData();
    formData.set("file", file);
    if (title.trim()) formData.set("title", title.trim());
    formData.set("classification", classification);
    const result = await upload.run(formData);
    if (result.ok) {
      formRef.current?.reset();
      setFile(null);
      setTitle("");
      onUploaded();
    }
  }

  return (
    <form ref={formRef} onSubmit={onSubmit} className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="upload-file">File (.md or .txt)</Label>
        <Input
          id="upload-file"
          type="file"
          accept=".md,.txt,text/markdown,text/plain"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          className="h-auto py-1.5 file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-2 file:py-1 file:text-xs"
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="upload-title">Title (optional)</Label>
        <Input
          id="upload-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="upload-classification">Classification</Label>
        <NativeSelect
          id="upload-classification"
          value={classification}
          onChange={(event) =>
            setClassification(event.target.value as Classification)
          }
        >
          {CLASSIFICATIONS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </div>
      <Button
        type="submit"
        disabled={!file || upload.pending}
        className="w-full"
      >
        <Upload className="size-4" aria-hidden />
        {upload.pending ? "Uploading…" : "Upload"}
      </Button>
      {/* 413 payload_too_large / 429 cap_exceeded messages are shown verbatim. */}
      {upload.error && (
        <ErrorState error={upload.error} title="Upload rejected" />
      )}
      {upload.data && !upload.pending && !upload.error && (
        <p className="text-sm text-emerald-700">
          Uploaded “{upload.data.title}” · ingest {upload.data.ingest_status}
        </p>
      )}
    </form>
  );
}
