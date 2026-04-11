"use client";

import { useRouter } from "next/navigation";
import { useProfile } from "@/hooks/useProfile";
import { ProfileForm } from "@/components/profile/ProfileForm";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { ArrowLeft } from "@phosphor-icons/react";

export default function ProfileEditPage() {
  const router = useRouter();
  const { profile, loading, updateProfile } = useProfile();

  if (loading) return <LoadingSpinner size={48} className="flex-1 py-20" />;

  return (
    <div className="flex-1 px-4 py-6 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push("/profile")}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft size={24} />
        </button>
        <h1 className="text-2xl font-bold">Edit Profile</h1>
      </div>
      <ProfileForm
        initialData={profile ? {
          name: profile.name,
          gender: profile.gender,
          interestedIn: profile.interestedIn,
          bio: profile.bio ?? "",
          interests: profile.interests ?? [],
          location: profile.location,
        } : undefined}
        onSubmit={async (data) => {
          await updateProfile(data);
          router.push("/profile");
        }}
        submitLabel="Save Changes"
      />
    </div>
  );
}
