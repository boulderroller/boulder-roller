import crown from "@/assets/rankmarks/rank01_crown@2x.png";
import laurel from "@/assets/rankmarks/rank02_laurel@2x.png";
import cobble from "@/assets/rankmarks/rank03_cobble@2x.png";
export default function RankMark({ rank }: { rank?: number }) {
  const image =
    rank === 1 ? crown : rank === 2 ? laurel : rank === 3 ? cobble : null;
  return (
    <span className="rank-mark">
      {image ? <img src={image} alt="" /> : rank && rank > 3 ? rank : null}
    </span>
  );
}
