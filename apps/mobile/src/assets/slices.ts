import angry from "@slices/avatar/expressions/angry@3x.png";
import happy from "@slices/avatar/expressions/happy@3x.png";
import idle from "@slices/avatar/expressions/idle@3x.png";
import sad from "@slices/avatar/expressions/sad@3x.png";
import shy from "@slices/avatar/expressions/shy@3x.png";
import surprised from "@slices/avatar/expressions/surprised@3x.png";
import thinking from "@slices/avatar/expressions/thinking@3x.png";
import wink from "@slices/avatar/expressions/wink@3x.png";
import blueBlob from "@slices/background_shapes/blue@3x.png";
import creamBlob from "@slices/background_shapes/cream@3x.png";
import lavenderBlob from "@slices/background_shapes/lavender@3x.png";
import mintBlob from "@slices/background_shapes/mint@3x.png";
import pinkBlob from "@slices/background_shapes/pink@3x.png";
import skyDot from "@slices/background_shapes/sky_dot@3x.png";
import yellowBlob from "@slices/background_shapes/yellow@3x.png";
import crown from "@slices/decorations/crown@3x.png";
import curveBlue from "@slices/decorations/curve_blue@3x.png";
import curvePurple from "@slices/decorations/curve_purple@3x.png";
import heartLarge from "@slices/decorations/heart_large@3x.png";
import heartSmall from "@slices/decorations/heart_small@3x.png";
import raysMint from "@slices/decorations/rays_mint@3x.png";
import raysPurple from "@slices/decorations/rays_purple@3x.png";
import starLarge from "@slices/decorations/star_large@3x.png";
import starSmall from "@slices/decorations/star_small@3x.png";
import back from "@slices/icons/actions/back@3x.png";
import image from "@slices/icons/actions/image@3x.png";
import moreAction from "@slices/icons/actions/more@3x.png";
import send from "@slices/icons/actions/send@3x.png";
import bell from "@slices/icons/features/bell@3x.png";
import chatSettings from "@slices/icons/features/chat_settings@3x.png";
import chevron from "@slices/icons/features/chevron@3x.png";
import email from "@slices/icons/features/email@3x.png";
import info from "@slices/icons/features/info@3x.png";
import lock from "@slices/icons/features/lock@3x.png";
import moon from "@slices/icons/features/moon@3x.png";
import palette from "@slices/icons/features/palette@3x.png";
import privacy from "@slices/icons/features/privacy@3x.png";
import profile from "@slices/icons/features/profile@3x.png";
import settings from "@slices/icons/features/settings@3x.png";
import support from "@slices/icons/features/support@3x.png";
import chatDefault from "@slices/icons/navigation/chat_default@3x.png";
import chatSelected from "@slices/icons/navigation/chat_selected@3x.png";
import moreDefault from "@slices/icons/navigation/more_default@3x.png";
import moreSelected from "@slices/icons/navigation/more_selected@3x.png";
import voiceDefault from "@slices/icons/navigation/voice_default@3x.png";
import voiceSelected from "@slices/icons/navigation/voice_selected@3x.png";

export const assets = {
  angry,
  happy,
  idle,
  sad,
  shy,
  surprised,
  thinking,
  wink,
  blueBlob,
  creamBlob,
  lavenderBlob,
  mintBlob,
  pinkBlob,
  skyDot,
  yellowBlob,
  crown,
  curveBlue,
  curvePurple,
  heartLarge,
  heartSmall,
  raysMint,
  raysPurple,
  starLarge,
  starSmall,
  back,
  image,
  moreAction,
  send,
  bell,
  chatSettings,
  chevron,
  email,
  info,
  lock,
  moon,
  palette,
  privacy,
  profile,
  settings,
  support,
  chatDefault,
  chatSelected,
  moreDefault,
  moreSelected,
  voiceDefault,
  voiceSelected,
} as const;

export type AvatarExpression = "wink" | "happy" | "idle" | "sad" | "shy" | "surprised" | "thinking" | "angry";

const expressions: Record<AvatarExpression, string> = {
  wink,
  happy,
  idle,
  sad,
  shy,
  surprised,
  thinking,
  angry,
};

export function avatarSource(expression: AvatarExpression): string {
  return expressions[expression];
}
