"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Tailor" },
  { href: "/resume", label: "Base Resume" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const path = usePathname();
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => {
    api.health()
      .then((h) => {
        const p: string[] = [];
        if (!h.latex_available) p.push(`LaTeX engine "${h.latex_engine}" is not installed on the backend.`);
        setProblems(p);
      })
      .catch((e) => setProblems([e.message]));
  }, []);

  return (
    <>
      <nav className="nav">
        <div className="container nav-inner">
          <span className="brand">Resume Tailor</span>
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>{l.label}</Link>
          ))}
        </div>
      </nav>
      {problems.length > 0 && (
        <div className="container">
          <div className="alert error">{problems.map((p) => <div key={p}>{p}</div>)}</div>
        </div>
      )}
    </>
  );
}
