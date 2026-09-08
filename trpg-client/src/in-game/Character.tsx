import characterImages from "../assets/人物"; //从assets里面一次性找到所有人物
import type { chat } from "../types/gametype"; //引入角色类型
import CharacterTransition from "./CharacterTransition";
import "../styles/Character.css"; //css

function getCharacterImage(name: string, expression: string) {
  const path = `./${name}/${expression}.png`;
  const n_and_e = characterImages[path] as string | undefined;
  if (n_and_e) {
    return n_and_e
  }
  const just_n = characterImages[`./${name}/正常.png`] as string | undefined;
  if (just_n) {
    return just_n
  }
  return undefined
}

//需要放大的人物
const character_height_st = new Set(["万里鹏程","龙渊"])

//角色绘制函数（等着被GameScene传参调与用）
function Character(props: chat) {
  const image = getCharacterImage(props.speaker, props.expression);
  if (image){
    let character_style: string = "character"

  if (character_height_st.has(props.speaker)) {
    character_style = "character_for_bigger"
  }

  return <CharacterTransition image={image} className={character_style} />;
  }
  
}

export default Character;
