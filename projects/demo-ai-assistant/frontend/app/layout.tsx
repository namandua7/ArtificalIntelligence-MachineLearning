import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Demo AI Assistant Blog",
  description: "A personal blog with a RAG-powered AI assistant",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-gray-200">
          <nav className="max-w-3xl mx-auto px-4 py-4 flex items-center gap-6">
            <Link href="/" className="font-bold text-lg">
              Demo Blog
            </Link>
            <Link href="/" className="text-sm text-gray-600 hover:text-gray-900">
              Posts
            </Link>
            <Link href="/assistant" className="text-sm text-gray-600 hover:text-gray-900">
              Assistant
            </Link>
            <Link href="/admin" className="text-sm text-gray-600 hover:text-gray-900 ml-auto">
              Admin
            </Link>
          </nav>
        </header>
        <main className="max-w-3xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
