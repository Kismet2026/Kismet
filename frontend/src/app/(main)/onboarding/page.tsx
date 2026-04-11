"use client";

import { useRouter } from "next/navigation";
import { ProfileForm } from "@/components/profile/ProfileForm";
import { useProfile } from "@/hooks/useProfile";
import { Sparkle } from "@phosphor-icons/react";

export default function OnboardingPage() {
  const router = useRouter();
  const { createProfile } = useProfile();

  return (
    <div className="flex-1 px-4 py-6 max-w-md mx-auto w-full">
      <div className="text-center mb-6">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
          <Sparkle size={24} className="text-primary" weight="fill" />
        </div>
        <h1 className="text-2xl font-bold">Set Up Your Profile</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Tell us about yourself to find your best matches
        </p>
      </div>
      <ProfileForm
        onSubmit={async (data) => {
          const birthDate = localStorage.getItem("kismet_birth_date") ?? "";
          await createProfile({ ...data, birthDate });
          router.push("/onboarding/photos");
        }}
        submitLabel="Next: Add Photos"
      />
    </div>
  );
}
