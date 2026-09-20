interface LogoProps {
	readonly type: "square" | "rectangle";
	readonly className?: string;
	readonly alt?: string;
}

/**
 * Logo component for Skra
 * For rectangle type: shows icon + text
 * For square type: shows icon only
 */
export function Logo({ type, className = "", alt = "Skra" }: LogoProps) {
	const defaultLogo = "/logo.svg";

	if (type === "rectangle") {
		return (
			<div className="flex items-center gap-2">
				<img src={defaultLogo} alt={alt} className="h-8 w-8" />
				<span className="hidden sm:inline-block font-semibold">
					Skra
				</span>
			</div>
		);
	}

	// Square type - just the icon
	return <img src={defaultLogo} alt={alt} className={className || "h-10 w-10"} />;
}
