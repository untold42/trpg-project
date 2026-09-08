import { useLayoutEffect, useRef, useState } from "react";

type CharacterLayer = {
  image: string | undefined;
  className: string;
};

type CharacterTransitionProps = CharacterLayer;

function CharacterTransition({ image, className }: CharacterTransitionProps) {
  const initialLayer: CharacterLayer = { image, className };
  const currentLayerRef = useRef(initialLayer);
  const [currentLayer, setCurrentLayer] = useState(initialLayer);
  const [previousLayer, setPreviousLayer] = useState<CharacterLayer | null>(null);

  useLayoutEffect(() => {
    const oldLayer = currentLayerRef.current;

    if (oldLayer.image === image && oldLayer.className === className) {
      return;
    }

    const nextLayer: CharacterLayer = { image, className };

    setPreviousLayer(oldLayer);

    const timer = window.setTimeout(() => {
      setPreviousLayer(null);
      setCurrentLayer(nextLayer);
      currentLayerRef.current = nextLayer;
    }, 175);

    return () => window.clearTimeout(timer);
  }, [image, className]);

  return previousLayer ? (
    <img
      src={previousLayer.image}
      className={`${previousLayer.className} character-fade-layer character-fade-out`}
      alt=""
    />
  ) : (
    <img
      src={currentLayer.image}
      className={`${currentLayer.className} character-fade-layer character-fade-in`}
      alt=""
    />
  );
}

export default CharacterTransition;
