import { useEffect, useState } from "react";
import "../styles/GooseAnimation.css";

const frames = Object.values(
    import.meta.glob("../assets/动画/大雁/*.png", {
        eager: true,
        import: "default",
    })
).sort();

type goo = {
    specific: string
}

function GooseAnimation({specific}: goo) {
    //将分散的大雁图组成一个动画
    const [index, setIndex] = useState(0);

    useEffect(() => {
        const timer = setInterval(() => {
            setIndex((prev) => (prev + 1) % frames.length);
        }, 150); //调节帧数

        return () => clearInterval(timer);
    }, []);

    return (
        <div className={specific}>
            <img src={frames[index] as string} />
        </div>
    );
}

export default GooseAnimation;