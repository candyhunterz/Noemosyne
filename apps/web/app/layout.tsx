import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Noemosyne",
  description: "Inspectable epistemic memory",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header>
          <nav>
            <strong><Link href="/">NOEMOSYNE</Link></strong>
            <Link href="/claims">Claims</Link>
            <Link href="/review">Review</Link>
            <Link href="/activity">Activity</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
