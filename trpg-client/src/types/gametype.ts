export type chat = {
  type: "chat";
  speaker: string;
  expression: string;
  content: string;
};

export type narration = {
  type: "narration"
  content: string;
}

export type bg={
  type: "bg"
  position: string;
  time: string;
}

export type instruction = chat | narration | bg;
