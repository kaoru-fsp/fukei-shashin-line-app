import React from "react";
import LogoLandscapeSvg from "../assets/logo_fukeishashin-PUB.svg?react";
import LogoIconSvg from "../assets/logo_kaze.svg?react";

interface LogoProps {
  variant?: "bright" | "dark" | "kaze";
  className?: string;
}

/**
 * BrandLogo component that renders the SVG logos.
 * Optimized for both desktop and mobile.
 */
export const LogoLandscape: React.FC<LogoProps> = ({ variant = "dark", className = "h-12 w-auto" }) => {
  return (
    <LogoLandscapeSvg 
      className={`${className} logo-${variant} will-change-transform`} 
      aria-labelledby="logoTitle"
      role="img"
    />
  );
};

export const LogoIcon: React.FC<LogoProps> = ({ variant = "dark", className = "h-10 w-auto" }) => {
  return (
    <LogoIconSvg 
      className={`${className} logo-${variant} will-change-transform`} 
      aria-labelledby="iconTitle"
      role="img"
    />
  );
};
