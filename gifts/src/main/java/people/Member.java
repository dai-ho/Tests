package people;

import java.util.ArrayList;
import java.util.List;

public class Member {
	private String name;
	private Member partner;
	private List<Member> exclusions;
	private Group group;

	public Member(String name, Group group) {
		this.name = name;
		group.addMember(this);
		this.group = group;
		exclusions = new ArrayList<Member>();
		exclusions.add(this);
	}

	public String getName() {
		return name;
	}

	public Member getPartner() {
		return partner;
	}

	public List<Member> getExclusions() {
		return exclusions;
	}

	public Group getGroup() {
		return group;
	}

	public void exclude(Member m) {
		exclusions.add(m);
	}

	public void setPartner(Member partner) {
		this.partner = partner;
		if (partner.getPartner() == null) {
			partner.setPartner(this);
		}
	}

	@Override
	public String toString() {
		String s = name + "(" + super.toString() + ")";
		return s;
	}
}
