import "../styles/ArtViewer.css";

// ------------------------------------------------------------
// 画作浮层：后端主动发起（server→GM push）呈现的画，展示在**对话框正上方**。
//   - 容器 pointer-events:none → 不挡对话框点击；只有画本身可交互；
//   - 关掉只靠右上角「×」（留存于 /arts，可另开画作页看）。
// ------------------------------------------------------------

export type ArtInfo = { 图片: string; 题?: string; 作者?: string };

type Props = { art: ArtInfo | null; onClose: () => void };

export default function ArtViewer({ art, onClose }: Props) {
    if (!art) return null;
    return (
        <div className="art-overlay">
            <div className="art-card">
                <button className="art-close" onClick={onClose} title="收起">×</button>
                <img className="art-img" src={art.图片} alt={art.题 || "画作"} />
                {(art.作者 || art.题) && (
                    <div className="art-caption">
                        {art.作者 ? `${art.作者} 作` : ""}
                        {art.题 ? `${art.作者 ? " · " : ""}${art.题}` : ""}
                    </div>
                )}
            </div>
        </div>
    );
}
