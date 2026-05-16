import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  applicationName: "Performance OS",
  title: "Performance OS",
  description: "A polished frontend prototype for recovery, nutrition, and training optimization.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Performance OS",
  },
  formatDetection: {
    telephone: false,
  },
  icons: {
    // Performance OS heart logo. The ?v= query busts stale favicon caches.
    icon: [
      { url: "/icons/favicon-32x32.png?v=3", sizes: "32x32", type: "image/png" },
      { url: "/icons/favicon-16x16.png?v=3", sizes: "16x16", type: "image/png" },
      { url: "/icons/android-chrome-192x192.png?v=3", sizes: "192x192", type: "image/png" },
      { url: "/icons/android-chrome-512x512.png?v=3", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png?v=3", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  themeColor: "#07080b",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
