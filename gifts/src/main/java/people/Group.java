package people;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

import org.apache.commons.math3.util.FastMath;

public class Group implements Comparable<Group> , Comparator<Group>{

	final List<Member> members;

	public Group() {
		members = new ArrayList<Member>();
	}

	public void addMember(Member m) {
		members.add(m);
	}

	public boolean isInGroup(Member m) {
		return members.contains(m);
	}

	public int getSize() {
		return members.size();
	}
	
	public List<Member> getMembers(){
		return members;
	}

	public int compareTo(Group o) {
		int res;
		if (o == null) {
			res = -1;
		} else {
			res = (int) FastMath.signum(getSize() - o.getSize());
		}
		return res;
	}

	public int compare(Group o1, Group o2) {
		return o1.compareTo(o2);
	}
}
