import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EcoEvidence · 文献证据召回工作台",
  description:
    "从自由研究需求到可量化证据召回评估的本地科学文献工作台。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
