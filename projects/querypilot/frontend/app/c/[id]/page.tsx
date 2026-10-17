import { redirect } from "next/navigation";

export default function WorkspaceIndex({ params }: { params: { id: string } }) {
  redirect(`/c/${params.id}/ask`);
}
