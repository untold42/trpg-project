import { useLayoutEffect, useRef, useState } from "react";

type BackgroundTransitionProps = {
  image: string;
};

function BackgroundTransition({ image }: BackgroundTransitionProps) {
  const currentImageRef = useRef(image);
  const [currentImage, setCurrentImage] = useState(image);
  const [previousImage, setPreviousImage] = useState<string | null>(null);

  useLayoutEffect(() => {
    const oldImage = currentImageRef.current;

    if (oldImage === image) {
      return;
    }

    setPreviousImage(oldImage);

    const timer = window.setTimeout(() => {
      setPreviousImage(null);
      setCurrentImage(image);
      currentImageRef.current = image;
    }, 1000);

    return () => window.clearTimeout(timer);
  }, [image]);

  return previousImage ? (
    <>
      <img
        src={previousImage}
        className="background-image background-fade-layer background-fade-out"
        alt=""
      />

      <img
        src={image}
        className="background-image background-fade-layer background-fade-in"
        alt=""
      />
    </>
  ) : (
    <img
      src={currentImage}
      className="background-image"
      alt=""
    />
  );
}

export default BackgroundTransition;