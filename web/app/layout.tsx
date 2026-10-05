import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "5인 미만 노무 안내",
  description: "소규모 사업장 사장님을 위한 노무 법령 안내",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
