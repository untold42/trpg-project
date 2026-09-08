import { useEffect, useState } from "react";
import type { chat, narration } from "../types/gametype";
import "../styles/DialogueBox.css";

function DialogueBox(props: (chat | narration) & { onAdvance: () => void; }) {
  if (props.type == 'chat') {

    const [displayedContent, setDisplayedContent] = useState(""); // 已经显示到屏幕上的文字；开始时是空的
    //useEffect用于实现文字的流式输出
    useEffect(() => {
      let currentIndex = 0;
      setDisplayedContent("");// 切换到新的一句对话时，先清空旧文字
      // 每 50 毫秒多显示一个字
      const timer = window.setInterval(() => {
        currentIndex += 1;
        // slice(0, currentIndex) 的意思是：
        // 从第 0 个字开始，取到 currentIndex 为止
        setDisplayedContent(props.content.slice(0, currentIndex));
        // 全部文字显示完成后，停止计时器
        if (currentIndex >= props.content.length) {
          window.clearInterval(timer);
        }
      }, 20);
      // 换到下一句、或组件消失时，停止旧计时器
      return () => { window.clearInterval(timer); };
    }, [props.content]);

    return (
      <div className="dialogue-box" onClick={props.onAdvance}>
        <div className="dialogue-content">
          <span className="dialogue-speaker">
            {props.speaker}
          </span>

          <span className="dialogue-text" >
            {displayedContent}
          </span>
        </div>
      </div>
    );
  }
  else {
    const [displayedContent, setDisplayedContent] = useState(""); // 已经显示到屏幕上的文字；开始时是空的
    //useEffect用于实现文字的流式输出
    useEffect(() => {
      let currentIndex = 0;
      setDisplayedContent("");// 切换到新的一句对话时，先清空旧文字
      // 每 50 毫秒多显示一个字
      const timer = window.setInterval(() => {
        currentIndex += 1;
        // slice(0, currentIndex) 的意思是：
        // 从第 0 个字开始，取到 currentIndex 为止
        setDisplayedContent(props.content.slice(0, currentIndex));
        // 全部文字显示完成后，停止计时器
        if (currentIndex >= props.content.length) {
          window.clearInterval(timer);
        }
      }, 20);
      // 换到下一句、或组件消失时，停止旧计时器
      return () => { window.clearInterval(timer); };
    }, [props.content]);

    return (
      <div className="dialogue-box" onClick={props.onAdvance}>
        <div className="dialogue-content">
          <span className="dialogue-speaker">
            旁白
          </span>

          <span className="dialogue-text" >
            {displayedContent}
          </span>
        </div>
      </div>
    );
  }
}

export default DialogueBox;
