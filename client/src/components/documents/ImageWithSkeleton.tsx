import { useState, useEffect } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { cn } from "@/lib/utils";

function resolveAuthenticatedImageUrl(src: string): URL | null {
  try {
    const url = new URL(src, window.location.origin);
    if (url.origin !== window.location.origin) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

export function ImageWithSkeleton({ node }: NodeViewProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);

  const { src, alt, title } = node.attrs;

  // Fetch image with auth headers and convert to blob URL
  useEffect(() => {
    if (!src) {
      setHasError(true);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    let objectUrl: string | null = null;

    const fetchImage = async () => {
      try {
        const imageUrl = resolveAuthenticatedImageUrl(src);
        if (!imageUrl) {
          throw new Error("Refusing to fetch cross-origin document image");
        }

        // Session authenticates via HttpOnly cookies (issue #90).
        const response = await fetch(imageUrl.toString(), {
          credentials: "include",
        });

        if (!response.ok) {
          throw new Error(`Failed to load image: ${response.status}`);
        }

        const blob = await response.blob();

        if (cancelled) {
          return;
        }

        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      } catch (error) {
        console.error("Image fetch failed:", error);
        if (!cancelled) {
          setHasError(true);
          setIsLoading(false);
        }
      }
    };

    fetchImage();

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [src]);

  // Clean up blob URL when component unmounts or URL changes
  useEffect(() => {
    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [blobUrl]);

  const handleLoad = () => {
    setIsLoading(false);
  };

  const handleError = () => {
    setIsLoading(false);
    setHasError(true);
  };

  if (hasError) {
    return (
      <NodeViewWrapper className="my-4">
        <div className="flex items-center justify-center h-32 bg-muted/50 rounded-md border border-dashed">
          <span className="text-sm text-muted-foreground">
            Failed to load image
          </span>
        </div>
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper className="my-4">
      <div className="relative inline-block max-w-full">
        {/* Skeleton placeholder */}
        {isLoading && (
          <div
            className="animate-pulse rounded-md bg-primary/10"
            style={{ minHeight: "100px", minWidth: "200px" }}
          />
        )}

        {/* Actual image - only render once we have the blob URL */}
        {blobUrl && (
          <img
            src={blobUrl}
            alt={alt || ""}
            title={title || ""}
            onLoad={handleLoad}
            onError={handleError}
            className={cn(
              "rounded-md max-w-full transition-opacity duration-300",
              isLoading ? "opacity-0 absolute inset-0" : "opacity-100"
            )}
          />
        )}
      </div>
    </NodeViewWrapper>
  );
}
